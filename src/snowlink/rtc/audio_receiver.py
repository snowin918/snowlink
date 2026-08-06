"""Remote audio track consumer, ring buffer, and playback sink for Experiment F.

Pipeline
--------
Remote aiortc audio track
  → continuous ``await track.recv()`` consumer (async task)
  → format validation / float32 conversion
  → bounded :class:`AudioRingBuffer`
  → playback worker thread **or** no-playback drain
  → metrics (PTS, tone, buffer underrun/overrun)

Playback never controls how quickly the WebRTC track is drained.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from snowlink.media.audio_format import apply_gain, samples_per_frame
from snowlink.media.audio_ring_buffer import AudioRingBuffer
from snowlink.rtc.audio_metrics import PtsValidator, PulseDetector, ToneAnalyzer
from snowlink.rtc.errors import WebRTCError, failure_for
from snowlink.rtc.models import DEFAULT_BUFFER_TARGET_MS

logger = logging.getLogger(__name__)


def audio_frame_to_float32(frame: Any) -> NDArray[np.float32]:
    """Convert a PyAV / aiortc AudioFrame to interleaved float32 ``(n, ch)``."""
    try:
        # Prefer ndarray path when available (layout-aware).
        arr = frame.to_ndarray()
    except Exception:
        arr = None
    if arr is not None:
        data = np.asarray(arr)
        # PyAV may return planar (channels, samples) or interleaved.
        layout = getattr(frame, "layout", None)
        channels = int(getattr(layout, "nb_channels", 0) or 0)
        if data.ndim == 1:
            if channels <= 1:
                return data.reshape(-1, 1).astype(np.float32) / (
                    32768.0 if data.dtype == np.int16 else 1.0
                )
            # Interleaved packed.
            if data.dtype == np.int16:
                f = data.astype(np.float32) / 32768.0
            else:
                f = data.astype(np.float32)
            if channels > 1:
                usable = (f.size // channels) * channels
                return f[:usable].reshape(-1, channels)
            return f.reshape(-1, 1)
        if data.ndim == 2:
            # Planar: (channels, samples) → interleaved.
            if data.shape[0] <= 8 and (channels == 0 or data.shape[0] == channels):
                planar = data
                if planar.dtype == np.int16:
                    planar = planar.astype(np.float32) / 32768.0
                else:
                    planar = planar.astype(np.float32)
                return np.ascontiguousarray(planar.T)
            # Already interleaved (samples, channels).
            if data.dtype == np.int16:
                return data.astype(np.float32) / 32768.0
            return data.astype(np.float32)

    # Fallback: raw plane bytes as s16 interleaved.
    raw = bytes(frame.planes[0])
    layout = getattr(frame, "layout", None)
    channels = int(getattr(layout, "nb_channels", 1) or 1)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    usable = (samples.size // channels) * channels
    return samples[:usable].reshape(-1, channels)


def validate_received_audio_frame(
    frame: Any,
    *,
    expected_sample_rate: int | None = None,
    expected_channels: int | None = None,
    expected_samples: int | None = None,
) -> tuple[int, int, str, int | None]:
    """Return (sample_rate, channels, format_name, pts); raise on hard invalidity."""
    sample_rate = int(getattr(frame, "sample_rate", 0) or 0)
    layout = getattr(frame, "layout", None)
    channels = int(getattr(layout, "nb_channels", 0) or 0)
    fmt = str(getattr(getattr(frame, "format", None), "name", "") or "unknown")
    pts = getattr(frame, "pts", None)
    pts_i = int(pts) if pts is not None else None
    samples = int(getattr(frame, "samples", 0) or 0)

    if sample_rate < 1 or channels < 1 or samples < 1:
        raise WebRTCError(
            failure_for(
                "INVALID_AUDIO_FRAME",
                f"Invalid audio frame (rate={sample_rate}, ch={channels}, samples={samples}).",
            )
        )
    if expected_sample_rate is not None and sample_rate != expected_sample_rate:
        # Soft: callers may still accept after recording mismatch.
        pass
    if expected_channels is not None and channels != expected_channels:
        pass
    if expected_samples is not None and samples != expected_samples:
        pass
    _ = expected_sample_rate, expected_channels, expected_samples
    return sample_rate, channels, fmt, pts_i


class RemoteAudioConsumer:
    """Continuously drain a remote audio track into a bounded ring buffer."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        frame_ms: int,
        buffer_target_ms: int = DEFAULT_BUFFER_TARGET_MS,
        expected_frequency_hz: float | None = None,
        signal: str = "sine",
        pulse_interval_ms: int = 1000,
        duration_s: float | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_ms = int(frame_ms)
        self.samples_per_frame = samples_per_frame(self.sample_rate, self.frame_ms)
        # Capacity ~2× target, minimum 120 ms, to stay bounded while absorbing jitter.
        capacity_ms = max(int(buffer_target_ms) * 2, 120)
        capacity_frames = max(
            self.samples_per_frame,
            int(self.sample_rate * capacity_ms / 1000.0),
        )
        self.buffer_target_ms = float(buffer_target_ms)
        self.buffer_capacity_ms = capacity_frames * 1000.0 / float(self.sample_rate)
        self.ring = AudioRingBuffer(capacity_frames, channels=self.channels)
        self.pts_validator = PtsValidator(expected_step=self.samples_per_frame)
        self.tone = ToneAnalyzer(
            sample_rate=self.sample_rate,
            expected_frequency_hz=expected_frequency_hz,
        )
        self.pulse: PulseDetector | None = None
        if signal == "pulse":
            self.pulse = PulseDetector(
                sample_rate=self.sample_rate,
                pulse_interval_ms=pulse_interval_ms,
                duration_s=duration_s,
            )

        self.frames_received = 0
        self.samples_received = 0
        self.frame_sample_count_mismatches = 0
        self.received_sample_rate: int | None = None
        self.received_channels: int | None = None
        self.received_format: str | None = None
        self.first_frame_at_ns: int | None = None
        self.last_frame_at_ns: int | None = None
        self.fill_ms_samples: list[float] = []
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._track: Any | None = None
        self._fatal: WebRTCError | None = None

    @property
    def fatal_error(self) -> WebRTCError | None:
        return self._fatal

    async def start(self, track: Any) -> None:
        if self._task is not None:
            return
        self._track = track
        self._stop.clear()
        self._task = asyncio.create_task(self._consume_loop(), name="remote-audio-consumer")

    async def stop(self) -> None:
        self._stop.set()
        self.ring.close()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        track = self._track
        self._track = None
        if track is not None:
            try:
                track.stop()
            except Exception:
                pass

    async def _consume_loop(self) -> None:
        assert self._track is not None
        track = self._track
        try:
            while not self._stop.is_set():
                try:
                    frame = await track.recv()
                except Exception as exc:
                    # MediaStreamError / connection end.
                    if not self._stop.is_set():
                        logger.debug("remote audio recv ended: %s", exc)
                    break
                self._handle_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fatal = WebRTCError(
                failure_for(
                    "UNEXPECTED_WEBRTC_AUDIO_ERROR",
                    "Remote audio consumer failed.",
                    exception=exc,
                )
            )

    def _handle_frame(self, frame: Any) -> None:
        try:
            rate, channels, fmt, pts = validate_received_audio_frame(frame)
        except WebRTCError as exc:
            self._fatal = exc
            return

        samples = int(getattr(frame, "samples", 0) or 0)
        if self.received_sample_rate is None:
            self.received_sample_rate = rate
            self.received_channels = channels
            self.received_format = fmt
        if samples != self.samples_per_frame:
            self.frame_sample_count_mismatches += 1

        self.pts_validator.observe(pts)
        pcm = audio_frame_to_float32(frame)

        # Channel adapt into ring buffer layout.
        if pcm.shape[1] != self.channels:
            if pcm.shape[1] == 1 and self.channels == 2:
                pcm = np.repeat(pcm, 2, axis=1)
            elif pcm.shape[1] == 2 and self.channels == 1:
                pcm = np.mean(pcm, axis=1, keepdims=True).astype(np.float32)
            else:
                out = np.zeros((pcm.shape[0], self.channels), dtype=np.float32)
                n = min(self.channels, pcm.shape[1])
                out[:, :n] = pcm[:, :n]
                pcm = out

        # Resample-ish: if rate differs, linear resample (rare with Opus@48k).
        if rate != self.sample_rate and pcm.shape[0] > 0:
            duration = pcm.shape[0] / float(rate)
            target_n = max(1, int(round(duration * self.sample_rate)))
            src_x = np.linspace(0.0, 1.0, pcm.shape[0], endpoint=False)
            dst_x = np.linspace(0.0, 1.0, target_n, endpoint=False)
            resampled = np.empty((target_n, self.channels), dtype=np.float32)
            for ch in range(self.channels):
                resampled[:, ch] = np.interp(dst_x, src_x, pcm[:, ch]).astype(np.float32)
            pcm = resampled

        self.ring.write(pcm)
        fill = self.ring.fill_frames()
        self.fill_ms_samples.append(fill * 1000.0 / float(self.sample_rate))

        self.tone.observe(pcm)
        if self.pulse is not None:
            self.pulse.observe(pcm)

        now = time.perf_counter_ns()
        if self.first_frame_at_ns is None:
            self.first_frame_at_ns = now
        self.last_frame_at_ns = now
        self.frames_received += 1
        self.samples_received += int(pcm.shape[0])


class PlaybackWorker:
    """Pull from the ring buffer on a wall-clock schedule for WASAPI playback."""

    def __init__(
        self,
        ring: AudioRingBuffer,
        *,
        sample_rate: int,
        channels: int,
        frame_ms: int,
        gain: float = 0.25,
        muted: bool = False,
        write_pcm: Callable[[NDArray[np.float32]], None] | None = None,
        enabled: bool = True,
    ) -> None:
        self.ring = ring
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_samples = samples_per_frame(sample_rate, frame_ms)
        self.frame_duration_s = self.frame_samples / float(sample_rate)
        self.gain = float(gain)
        self.muted = bool(muted)
        self.write_pcm = write_pcm
        self.enabled = bool(enabled)
        self.samples_played = 0
        self.silence_samples_inserted = 0
        self.underruns = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fatal: BaseException | None = None

    @property
    def fatal_error(self) -> BaseException | None:
        return self._fatal

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="exp-f-audio-playback",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        self.ring.close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        start = time.perf_counter()
        index = 0
        try:
            while not self._stop.is_set():
                target = start + index * self.frame_duration_s
                delay = target - time.perf_counter()
                if delay > 0:
                    if self._stop.wait(timeout=delay):
                        break
                data, underrun = self.ring.read_exact(
                    self.frame_samples,
                    timeout=0.0,
                )
                if underrun:
                    self.underruns += 1
                    self.silence_samples_inserted += self.frame_samples
                pcm = apply_gain(data, self.gain, muted=self.muted or not self.enabled)
                if self.enabled and self.write_pcm is not None:
                    self.write_pcm(pcm)
                self.samples_played += self.frame_samples
                index += 1
        except BaseException as exc:
            self._fatal = exc
