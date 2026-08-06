"""Local WASAPI loopback → convert → playback pipeline for Experiment D.

Pipeline::

    WASAPI loopback callback
    → bounded AudioRingBuffer (native float32, drop-oldest)
    → channel / sample-format conversion
    → resample to target rate (48 kHz default)
    → fixed 20 ms frames with sample-driven PTS
    → optional local playback
    → metrics
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from snowlink.media.audio_errors import AudioError, AudioFailure, map_exception
from snowlink.media.audio_format import (
    AudioFormatConverter,
    apply_gain,
    is_silent_frame,
    peak_level,
    rms_level,
    samples_per_frame,
)
from snowlink.media.audio_metrics import AudioTimingAccumulator
from snowlink.media.audio_models import (
    AudioConfiguration,
    BufferStats,
    CaptureAudioStats,
    ConversionStats,
    ExperimentDResult,
    PlaybackStats,
    ResourceStats,
    utc_now_iso,
)
from snowlink.media.audio_playback import AudioPlayer
from snowlink.media.audio_ring_buffer import AudioRingBuffer
from snowlink.media.capture_metrics import ProcessResourceSampler, elapsed_s
from snowlink.media.loopback_capture import LoopbackCapture
from snowlink.platform_win.audio_endpoints import (
    AudioEndpointInfo,
    feedback_risk_warnings,
    require_pyaudio,
    resolve_loopback_device,
    resolve_playback_device,
)


@dataclass(slots=True)
class _RuntimeLevels:
    peak: float = 0.0
    rms_sum: float = 0.0
    rms_count: int = 0
    non_silent_frames: int = 0
    silence_frames: int = 0
    converted_frames: int = 0


@dataclass(slots=True)
class AudioPipelineSession:
    """Owns capture, conversion, optional playback, and shutdown sequencing."""

    config: AudioConfiguration
    capture_endpoint: AudioEndpointInfo | None = None
    playback_endpoint: AudioEndpointInfo | None = None
    ring: AudioRingBuffer | None = None
    capture: LoopbackCapture | None = None
    player: AudioPlayer | None = None
    converter: AudioFormatConverter | None = None
    timings: AudioTimingAccumulator = field(default_factory=AudioTimingAccumulator)
    resources: ProcessResourceSampler = field(default_factory=ProcessResourceSampler)
    levels: _RuntimeLevels = field(default_factory=_RuntimeLevels)
    warnings: list[str] = field(default_factory=list)
    errors: list[AudioFailure] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _worker: threading.Thread | None = None
    _worker_synth: threading.Thread | None = None
    _pa: Any | None = None
    _started_ns: int = 0
    _monitor_callback: Callable[[dict[str, Any]], None] | None = None
    # Synthetic injection for tests (bypass real WASAPI).
    synthetic_source: Callable[[], np.ndarray | None] | None = None

    def start(self) -> None:
        self._stop.clear()
        self._started_ns = time.perf_counter_ns()
        synthetic = self.synthetic_source is not None

        if synthetic:
            # Fully offline path for unit/integration tests (no WASAPI).
            native_rate = self.config.target_sample_rate
            native_ch = self.config.target_channels
            if self.capture_endpoint is None:
                self.capture_endpoint = AudioEndpointInfo(
                    index=0,
                    name="synthetic-loopback",
                    host_api="synthetic",
                    host_api_index=-1,
                    max_input_channels=native_ch,
                    max_output_channels=0,
                    default_sample_rate=float(native_rate),
                    is_wasapi=True,
                    is_loopback=True,
                    associated_output_name="synthetic-output",
                    associated_output_index=1,
                    is_default_output=False,
                    is_default_input=False,
                    can_capture=True,
                    can_playback=False,
                    kind="wasapi_loopback",
                )
        else:
            pyaudio = require_pyaudio()
            self._pa = pyaudio.PyAudio()
            self.capture_endpoint = resolve_loopback_device(
                self.config.capture_device, pa=self._pa
            )
            if self.config.enable_playback:
                self.playback_endpoint = resolve_playback_device(
                    self.config.playback_device, pa=self._pa
                )
                self.warnings.extend(
                    feedback_risk_warnings(
                        self.capture_endpoint, self.playback_endpoint
                    )
                )
            native_rate = int(self.capture_endpoint.default_sample_rate) or 48000
            native_ch = max(1, int(self.capture_endpoint.max_input_channels))

        capacity_frames = max(
            1,
            int(native_rate * self.config.buffer_capacity_ms / 1000.0),
        )
        self.ring = AudioRingBuffer(capacity_frames, channels=native_ch)
        self.converter = AudioFormatConverter(
            source_rate=native_rate,
            source_channels=native_ch,
            target_rate=self.config.target_sample_rate,
            target_channels=self.config.target_channels,
            frame_duration_ms=self.config.frame_duration_ms,
            output_sample_format=self.config.output_sample_format,
            prefer_pyav=not synthetic,
        )

        if synthetic:
            self._worker_synth = threading.Thread(
                target=self._synthetic_feed_loop,
                name="snowlink-audio-synth",
                daemon=True,
            )
            self._worker_synth.start()
        else:
            assert self._pa is not None and self.capture_endpoint is not None
            self.capture = LoopbackCapture(
                self.capture_endpoint,
                self.ring,
                pa=self._pa,
                frames_per_buffer=samples_per_frame(
                    native_rate, self.config.frame_duration_ms
                ),
                on_error=self._on_capture_error,
            )
            self.capture.open()
            self.capture.start()

        if (
            self.config.enable_playback
            and self.playback_endpoint is not None
            and not synthetic
        ):
            self.player = AudioPlayer(
                self.playback_endpoint,
                sample_rate=self.config.target_sample_rate,
                channels=self.config.target_channels,
                pa=self._pa,
                frames_per_buffer=samples_per_frame(
                    self.config.target_sample_rate, self.config.frame_duration_ms
                ),
            )
            self.player.open()
            self.player.start()

        self._worker = threading.Thread(
            target=self._process_loop,
            name="snowlink-audio-pipeline",
            daemon=True,
        )
        self._worker.start()

    def request_stop(self) -> None:
        self._stop.set()

    def shutdown(self, *, join_timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                pass
        if self.player is not None:
            try:
                self.player.stop()
            except Exception:
                pass
        if self.capture is not None:
            try:
                self.capture.close()
            except Exception:
                pass
        if self.player is not None:
            try:
                self.player.close()
            except Exception:
                pass
        if self.ring is not None:
            self.ring.close()
        if self._worker is not None:
            self._worker.join(timeout=join_timeout_s)
            self._worker = None
        if self._worker_synth is not None:
            self._worker_synth.join(timeout=join_timeout_s)
            self._worker_synth = None
        if self._pa is not None:
            # Capture/player may share pa; terminate once if they did not own it.
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def _on_capture_error(self, failure: AudioFailure) -> None:
        self.errors.append(failure)
        self._stop.set()

    def _synthetic_feed_loop(self) -> None:
        assert self.ring is not None and self.synthetic_source is not None
        while not self._stop.is_set():
            try:
                chunk = self.synthetic_source()
                if chunk is None:
                    time.sleep(0.005)
                    continue
                self.ring.write(np.asarray(chunk, dtype=np.float32))
            except Exception as exc:
                self.errors.append(map_exception(exc))
                self._stop.set()
                break

    def _process_loop(self) -> None:
        assert self.ring is not None and self.converter is not None
        native_rate = self.converter.source_rate
        read_frames = samples_per_frame(native_rate, self.config.frame_duration_ms)
        frame_period_s = self.config.frame_duration_ms / 1000.0
        next_report = time.perf_counter() + 1.0
        last_resource = time.perf_counter()

        while not self._stop.is_set():
            if self.capture is not None and self.capture.fatal_error is not None:
                if self.capture.fatal_error not in self.errors:
                    self.errors.append(self.capture.fatal_error)
                break
            if self.player is not None and self.player.fatal_error is not None:
                if self.player.fatal_error not in self.errors:
                    self.errors.append(self.player.fatal_error)
                break

            t0 = time.perf_counter_ns()
            timeout = frame_period_s * 1.5
            data, underrun = self.ring.read_exact(read_frames, timeout=timeout)
            fill = self.ring.fill_frames()
            fill_ms = (fill / float(native_rate)) * 1000.0 if native_rate else 0.0
            self.timings.add_fill_ms(fill_ms)
            self.timings.add_queue_delay_ms(fill_ms)

            try:
                if underrun:
                    # Missing data: emit silence frame, keep PTS continuous.
                    frame = self.converter.make_silence_frame(underrun_padding=True)
                    frames = [frame]
                else:
                    frames = self.converter.push(data)
            except AudioError as exc:
                self.errors.append(exc.failure)
                break
            except Exception as exc:
                self.errors.append(map_exception(exc))
                break

            for frame in frames:
                self.levels.converted_frames += 1
                # Level stats on float view
                if frame.sample_format == "s16":
                    f32 = frame.samples.astype(np.float32) / 32768.0
                else:
                    f32 = np.asarray(frame.samples, dtype=np.float32)
                if frame.is_underrun_padding:
                    self.levels.silence_frames += 1
                elif is_silent_frame(f32):
                    self.levels.silence_frames += 1
                else:
                    self.levels.non_silent_frames += 1
                pk = peak_level(f32)
                self.levels.peak = max(self.levels.peak, pk)
                self.levels.rms_sum += rms_level(f32)
                self.levels.rms_count += 1

                if self.config.enable_playback and self.player is not None:
                    try:
                        gained = apply_gain(
                            f32, self.config.gain, muted=self.config.muted
                        )
                        from snowlink.media.audio_format import AudioFrame, float32_to_s16

                        play_frame = AudioFrame(
                            pts=frame.pts,
                            samples=(
                                float32_to_s16(gained)
                                if frame.sample_format == "s16"
                                else gained
                            ),
                            sample_rate=frame.sample_rate,
                            channels=frame.channels,
                            sample_format=frame.sample_format,
                            is_silence=frame.is_silence,
                            is_underrun_padding=frame.is_underrun_padding,
                        )
                        self.player.write_frame(play_frame)
                    except AudioError as exc:
                        self.errors.append(exc.failure)
                        self._stop.set()
                        break

            t1 = time.perf_counter_ns()
            self.timings.add_processing_ns(t1 - t0)

            now = time.perf_counter()
            if now - last_resource >= 0.5:
                self.resources.sample()
                last_resource = now
            if self._monitor_callback is not None and now >= next_report:
                self._monitor_callback(self.monitor_snapshot())
                next_report = now + 1.0

            # Pace monitor-only slightly when ring is empty to avoid busy loop.
            if not self.config.enable_playback and underrun:
                time.sleep(0.001)

    def monitor_snapshot(self) -> dict[str, Any]:
        ring = self.ring
        cap = self.capture
        native_rate = (
            self.converter.source_rate
            if self.converter is not None
            else (cap.native_sample_rate if cap else 48000)
        )
        fill = ring.fill_frames() if ring else 0
        fill_ms = (fill / float(native_rate)) * 1000.0 if native_rate else 0.0
        return {
            "non_silent_detected": self.levels.non_silent_frames > 0,
            "peak_level": self.levels.peak,
            "rms_level": (
                self.levels.rms_sum / self.levels.rms_count
                if self.levels.rms_count
                else 0.0
            ),
            "captured_frames": self.levels.converted_frames,
            "captured_samples": cap.captured_samples if cap else 0,
            "estimated_input_sample_rate": native_rate,
            "buffer_fill_ms": fill_ms,
            "callback_errors": cap.read_errors if cap else 0,
            "underruns": ring.underrun_count() if ring else 0,
            "overruns": ring.overrun_count() if ring else 0,
        }

    def build_result(self, *, success: bool | None = None) -> ExperimentDResult:
        cap = self.capture
        conv = self.converter
        ring = self.ring
        player = self.player
        res = self.resources.finalize()
        ring_stats = ring.stats() if ring else None
        avg_fill = self.timings.average_fill_ms()
        peak_fill = self.timings.peak_fill_ms()
        if peak_fill is None and ring_stats is not None and conv is not None:
            peak_fill = (ring_stats.peak_fill_samples / float(conv.source_rate)) * 1000.0

        fatal_codes = {e.code for e in self.errors}
        ok = success if success is not None else (
            not fatal_codes
            or fatal_codes <= {"BUFFER_UNDERRUN", "BUFFER_OVERRUN"}
        )
        # Treat device / open failures as unsuccessful.
        hard = {
            "DEVICE_DISCONNECTED",
            "CAPTURE_OPEN_FAILED",
            "PLAYBACK_OPEN_FAILED",
            "CAPTURE_READ_FAILED",
            "PLAYBACK_WRITE_FAILED",
            "RESAMPLE_FAILED",
            "UNEXPECTED_AUDIO_ERROR",
            "PYAUDIO_WPATCH_NOT_INSTALLED",
            "WASAPI_NOT_AVAILABLE",
            "NO_LOOPBACK_DEVICE",
            "INVALID_CAPTURE_DEVICE",
            "INVALID_PLAYBACK_DEVICE",
        }
        if fatal_codes & hard:
            ok = False

        capacity_ms = float(self.config.buffer_capacity_ms)
        return ExperimentDResult(
            started_at_utc=utc_now_iso(),  # overwritten by runner when known
            completed_at_utc=utc_now_iso(),
            success=ok,
            configuration=self.config,
            capture=CaptureAudioStats(
                device_index=(
                    self.capture_endpoint.index if self.capture_endpoint else None
                ),
                device_name=(
                    self.capture_endpoint.name if self.capture_endpoint else ""
                ),
                native_sample_rate=cap.native_sample_rate if cap else (
                    conv.source_rate if conv else 0
                ),
                native_channels=cap.native_channels if cap else (
                    conv.source_channels if conv else 0
                ),
                native_sample_format=cap.native_sample_format if cap else "float32",
                captured_samples=cap.captured_samples if cap else (
                    conv.input_samples if conv else 0
                ),
                captured_frames=self.levels.converted_frames,
                capture_callbacks=cap.callbacks if cap else 0,
                non_silent_frames=self.levels.non_silent_frames,
                silence_frames=self.levels.silence_frames,
                peak_level=self.levels.peak,
                rms_average=(
                    self.levels.rms_sum / self.levels.rms_count
                    if self.levels.rms_count
                    else 0.0
                ),
                read_errors=cap.read_errors if cap else 0,
            ),
            conversion=ConversionStats(
                output_sample_rate=self.config.target_sample_rate,
                output_channels=self.config.target_channels,
                output_sample_format=self.config.output_sample_format,
                converted_samples=conv.output_samples if conv else 0,
                frame_duration_ms=self.config.frame_duration_ms,
                actual_frame_samples=(
                    conv.frame_samples if conv else samples_per_frame(
                        self.config.target_sample_rate, self.config.frame_duration_ms
                    )
                ),
                last_pts=(
                    conv.pts_clock.peek() - conv.frame_samples
                    if conv is not None and conv.pts_clock.peek() >= conv.frame_samples
                    else -1
                ),
            ),
            playback=PlaybackStats(
                device_index=(
                    self.playback_endpoint.index if self.playback_endpoint else None
                ),
                device_name=(
                    self.playback_endpoint.name if self.playback_endpoint else ""
                ),
                played_samples=player.played_samples if player else 0,
                playback_writes=player.writes if player else 0,
                write_errors=player.write_errors if player else 0,
            ),
            buffer=BufferStats(
                capacity_ms=capacity_ms,
                average_fill_ms=avg_fill,
                peak_fill_ms=peak_fill,
                underruns=ring_stats.underruns if ring_stats else 0,
                overruns=ring_stats.overruns if ring_stats else 0,
                dropped_samples=ring_stats.dropped_samples if ring_stats else 0,
            ),
            timing_ms=self.timings.to_timing_stats(),
            resources=ResourceStats(
                cpu_percent_average=res.cpu_percent_average,
                cpu_percent_peak=res.cpu_percent_peak,
                memory_mb_start=res.memory_mb_start,
                memory_mb_end=res.memory_mb_end,
                memory_mb_peak=res.memory_mb_peak,
            ),
            errors=[e.to_dict() for e in self.errors],
            warnings=list(self.warnings),
            details={
                "elapsed_s": elapsed_s(self._started_ns) if self._started_ns else 0.0,
                "local_pipeline_queue_delay_note": (
                    "timing_ms.queue_delay_* reflects ring-buffer fill, labeled as "
                    "local pipeline queue delay (not true end-to-end audio latency)."
                ),
            },
        )


def run_audio_pipeline(
    config: AudioConfiguration,
    *,
    honor_duration: bool = True,
    monitor_callback: Callable[[dict[str, Any]], None] | None = None,
    synthetic_source: Callable[[], np.ndarray | None] | None = None,
    started_at: str | None = None,
) -> tuple[int, ExperimentDResult]:
    """Run the pipeline until duration, stop, or fatal error."""
    started = started_at or utc_now_iso()
    session = AudioPipelineSession(config, synthetic_source=synthetic_source)
    session._monitor_callback = monitor_callback
    code = 0
    try:
        session.start()
        deadline = time.perf_counter() + config.duration_s
        while True:
            if session._stop.is_set():
                break
            if honor_duration and time.perf_counter() >= deadline:
                break
            if session.errors:
                hard = {
                    e.code
                    for e in session.errors
                    if e.code
                    not in {
                        "BUFFER_UNDERRUN",
                        "BUFFER_OVERRUN",
                    }
                }
                if hard:
                    break
            time.sleep(0.05)
    except KeyboardInterrupt:
        session.request_stop()
    except AudioError as exc:
        session.errors.append(exc.failure)
        code = 2
    except Exception as exc:
        session.errors.append(map_exception(exc))
        code = 2
    finally:
        session.shutdown()

    result = session.build_result()
    result.started_at_utc = started
    result.completed_at_utc = utc_now_iso()
    if not result.success:
        code = code or 1
    return code, result


def make_click_tone(
    *,
    sample_rate: int,
    channels: int,
    frequency_hz: float = 1000.0,
    duration_ms: float = 50.0,
    amplitude: float = 0.2,
) -> np.ndarray:
    """Generate a short conservative test click/tone (float32 interleaved)."""
    n = max(1, int(sample_rate * duration_ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    wave = (amplitude * np.sin(2.0 * np.pi * frequency_hz * t)).astype(np.float32)
    # Hann fade to avoid clicks at edges being excessively harsh.
    fade = min(n // 4, int(sample_rate * 0.005))
    if fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    if channels == 1:
        return wave.reshape(-1, 1)
    return np.repeat(wave.reshape(-1, 1), channels, axis=1)
