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
from collections import deque
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
    """Convert a PyAV / aiortc AudioFrame to interleaved float32 ``(n, ch)``.

    PyAV ``to_ndarray()`` layouts we must handle:

    - packed ``s16`` stereo → shape ``(1, samples * channels)``
    - planar ``s16p`` / ``fltp`` → shape ``(channels, samples)``
    - already interleaved → shape ``(samples, channels)``
    - mono → shape ``(1, samples)`` or ``(samples,)``
    """
    layout = getattr(frame, "layout", None)
    channels = int(getattr(layout, "nb_channels", 0) or 0)
    samples = int(getattr(frame, "samples", 0) or 0)

    try:
        arr = frame.to_ndarray()
    except Exception:
        arr = None

    if arr is not None:
        data = np.asarray(arr)

        def _as_float(x: NDArray[Any]) -> NDArray[np.float32]:
            if x.dtype == np.int16:
                return x.astype(np.float32) / 32768.0
            if x.dtype == np.int32:
                return x.astype(np.float32) / 2147483648.0
            return x.astype(np.float32)

        if data.ndim == 1:
            f = _as_float(data)
            if channels <= 1:
                return f.reshape(-1, 1)
            usable = (f.size // channels) * channels
            return f[:usable].reshape(-1, channels)

        if data.ndim == 2:
            # Packed interleaved in one row: (1, samples*channels) — common for s16.
            if (
                channels > 1
                and data.shape[0] == 1
                and data.shape[1] % channels == 0
            ):
                f = _as_float(data.reshape(-1))
                return f.reshape(-1, channels)

            # True planar: (channels, samples).
            if channels > 0 and data.shape[0] == channels:
                planar = _as_float(data)
                return np.ascontiguousarray(planar.T)

            # Already interleaved: (samples, channels).
            if channels > 0 and data.shape[1] == channels:
                return _as_float(data)

            # Mono planar-ish: (1, samples).
            if channels <= 1 and data.shape[0] == 1:
                return _as_float(data.reshape(-1, 1))

            # Last resort: if width matches sample count, treat as planar-ish.
            if samples > 0 and data.shape[1] == samples:
                return np.ascontiguousarray(_as_float(data).T)

            return _as_float(data)

    # Fallback: raw plane bytes as s16 interleaved.
    raw = bytes(frame.planes[0])
    channels = channels if channels >= 1 else 1
    decoded = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    usable = (decoded.size // channels) * channels
    return decoded[:usable].reshape(-1, channels)


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
        self.peak_level = 0.0
        self.received_sample_rate: int | None = None
        self.received_channels: int | None = None
        self.received_format: str | None = None
        self.first_frame_at_ns: int | None = None
        self.last_frame_at_ns: int | None = None
        # Bounded — live view can run for hours at ~50 appends/s.
        self.fill_ms_samples: deque[float] = deque(maxlen=600)
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
                        if self.frames_received == 0:
                            logger.warning(
                                "remote audio recv ended before any frames: %s", exc
                            )
                            self._fatal = WebRTCError(
                                failure_for(
                                    "UNEXPECTED_WEBRTC_AUDIO_ERROR",
                                    "Remote audio track ended before any frames arrived.",
                                    exception=exc,
                                )
                            )
                        else:
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
        try:
            peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
            if peak > self.peak_level:
                self.peak_level = peak
        except Exception:
            pass
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
    """Pull from the ring buffer on a wall-clock schedule for WASAPI playback.

    Waits for a short prebuffer before starting the wall clock so the first
    seconds are not pure underrun silence. If underruns persist, re-prebuffers
    and resets the clock instead of racing forever ahead of the receiver.

    When *playback_endpoint* is set, the WASAPI output stream is opened and
    written on this worker thread (required for reliable Windows WASAPI output).
    """

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
        controls: Any | None = None,
        prebuffer_ms: float = 80.0,
        rebuffer_after_underruns: int = 25,
        playback_endpoint: Any | None = None,
    ) -> None:
        self.ring = ring
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_samples = samples_per_frame(sample_rate, frame_ms)
        self.frame_duration_s = self.frame_samples / float(sample_rate)
        self.gain = float(gain)
        self.muted = bool(muted)
        self.controls = controls
        self.write_pcm = write_pcm
        self.enabled = bool(enabled)
        self.prebuffer_ms = float(prebuffer_ms)
        self.rebuffer_after_underruns = int(rebuffer_after_underruns)
        self.playback_endpoint = playback_endpoint
        self.samples_played = 0
        self.silence_samples_inserted = 0
        self.underruns = 0
        self.peak_level = 0.0
        self._player: Any | None = None
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
            name="snowlink-audio-playback",
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
        self._close_player()

    def _close_player(self) -> None:
        player = self._player
        self._player = None
        if player is None:
            return
        try:
            player.close()
        except Exception:
            logger.debug("playback player close failed", exc_info=True)

    def _prebuffer_frames(self) -> int:
        return max(
            self.frame_samples,
            int(self.sample_rate * self.prebuffer_ms / 1000.0),
        )

    def _wait_for_prebuffer(self) -> bool:
        """Block until the ring has enough audio, or stop is requested.

        Returns False if stopped before the target fill was reached.
        """
        target = self._prebuffer_frames()
        while not self._stop.is_set():
            if self.ring.closed:
                return False
            if self.ring.fill_frames() >= target:
                return True
            if self._stop.wait(timeout=0.005):
                return False
        return False

    def _open_player_on_worker_thread(self) -> None:
        if self.playback_endpoint is None:
            return
        from snowlink.media.audio_format import float32_to_s16
        from snowlink.media.audio_playback import AudioPlayer

        player = AudioPlayer(
            self.playback_endpoint,
            sample_rate=self.sample_rate,
            channels=self.channels,
            frames_per_buffer=self.frame_samples,
        )
        player.open()
        player.start()
        self._player = player

        def _write(pcm: NDArray[np.float32]) -> None:
            assert self._player is not None
            self._player.write_s16(float32_to_s16(pcm))

        self.write_pcm = _write

    def _run(self) -> None:
        try:
            # Fill the jitter buffer before opening WASAPI so a slow device open
            # cannot leave us blocked with an empty prebuffer forever.
            if not self._wait_for_prebuffer():
                return
            if self.playback_endpoint is not None:
                logger.info("PlaybackWorker prebuffer ready; opening WASAPI output")
                self._open_player_on_worker_thread()
            start = time.perf_counter()
            index = 0
            consecutive_underruns = 0
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
                    consecutive_underruns += 1
                    if consecutive_underruns >= self.rebuffer_after_underruns:
                        # Clock ran ahead of the jitter buffer — wait and resync.
                        if not self._wait_for_prebuffer():
                            break
                        start = time.perf_counter()
                        index = 0
                        consecutive_underruns = 0
                        continue
                else:
                    consecutive_underruns = 0
                    try:
                        peak = float(np.max(np.abs(data)))
                        if peak > self.peak_level:
                            self.peak_level = peak
                    except Exception:
                        pass
                gain = float(getattr(self.controls, "gain", self.gain))
                muted = bool(getattr(self.controls, "muted", self.muted))
                pcm = apply_gain(data, gain, muted=muted or not self.enabled)
                if self.enabled and self.write_pcm is not None:
                    self.write_pcm(pcm)
                self.samples_played += self.frame_samples
                index += 1
        except BaseException as exc:
            self._fatal = exc
            logger.exception("PlaybackWorker failed")
        finally:
            self._close_player()
