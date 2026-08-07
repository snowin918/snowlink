"""WASAPI loopback → aiortc AudioStreamTrack for Phase 2 screen+audio share.

Capture path
------------
WASAPI loopback callback → bounded :class:`AudioRingBuffer` (native float32)
  → :class:`AudioFormatConverter` (48 kHz / stereo / 20 ms / s16)
  → :class:`LoopbackAudioTrack.recv` (wall-clock paced; silence on underrun)
  → aiortc Opus encode

PTS is sample-driven via the converter clock (not wall clock).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from snowlink.media.audio_format import AudioFormatConverter, samples_per_frame
from snowlink.media.audio_models import (
    DEFAULT_BUFFER_MS,
    DEFAULT_FRAME_MS,
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
)
from snowlink.media.audio_ring_buffer import AudioRingBuffer
from snowlink.media.loopback_capture import LoopbackCapture
from snowlink.platform_win.audio_endpoints import (
    AudioEndpointInfo,
    require_pyaudio,
    resolve_loopback_device,
)
from snowlink.rtc.synthetic_audio import pcm_to_audio_frame, schedule_audio_index

try:
    from aiortc import AudioStreamTrack
    from aiortc.mediastreams import MediaStreamError
except ImportError as exc:  # pragma: no cover
    raise ImportError("aiortc is required for loopback audio tracks") from exc

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioPlaybackControls:
    """Mutable viewer playback controls (safe to flip from the UI thread)."""

    muted: bool = False
    gain: float = 0.25


@dataclass(slots=True)
class ShareAudioCapture:
    """Owns WASAPI loopback + ring + converter for a share session."""

    endpoint: AudioEndpointInfo
    ring: AudioRingBuffer
    converter: AudioFormatConverter
    capture: LoopbackCapture | None
    _pa: Any
    _owns_pa: bool
    sample_rate: int = TARGET_SAMPLE_RATE
    channels: int = TARGET_CHANNELS
    frame_ms: int = DEFAULT_FRAME_MS
    _synth_stop: Any = None

    @classmethod
    def start(
        cls,
        *,
        capture_device: str = "default",
        sample_rate: int = TARGET_SAMPLE_RATE,
        channels: int = TARGET_CHANNELS,
        frame_ms: int = DEFAULT_FRAME_MS,
        buffer_capacity_ms: int = DEFAULT_BUFFER_MS,
        pa: Any | None = None,
        synthetic_feed: Callable[[], np.ndarray | None] | None = None,
    ) -> ShareAudioCapture:
        """Open loopback (or synthetic feed) and return a ready capture bundle."""
        if synthetic_feed is not None:
            native_rate = sample_rate
            native_ch = channels
            endpoint = AudioEndpointInfo(
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
            owns_pa = False
            pa_obj = None
        else:
            pyaudio = require_pyaudio()
            owns_pa = pa is None
            pa_obj = pa if pa is not None else pyaudio.PyAudio()
            endpoint = resolve_loopback_device(capture_device, pa=pa_obj)
            native_rate = int(endpoint.default_sample_rate) or sample_rate
            native_ch = max(1, int(endpoint.max_input_channels))

        capacity_frames = max(1, int(native_rate * buffer_capacity_ms / 1000.0))
        ring = AudioRingBuffer(capacity_frames, channels=native_ch)
        converter = AudioFormatConverter(
            source_rate=native_rate,
            source_channels=native_ch,
            target_rate=sample_rate,
            target_channels=channels,
            frame_duration_ms=frame_ms,
            output_sample_format="s16",
            prefer_pyav=synthetic_feed is None,
        )

        capture_obj: LoopbackCapture | None = None
        synth_stop: Any = None
        if synthetic_feed is None:
            assert pa_obj is not None
            capture_obj = LoopbackCapture(
                endpoint,
                ring,
                pa=pa_obj,
                frames_per_buffer=samples_per_frame(native_rate, frame_ms),
            )
            capture_obj.open()
            capture_obj.start()
        else:
            # Background synthetic feeder for unit tests (no WASAPI).
            import threading

            synth_stop = threading.Event()

            def _feed() -> None:
                frame_n = samples_per_frame(native_rate, frame_ms)
                interval = frame_n / float(native_rate)
                next_t = time.perf_counter()
                while not synth_stop.is_set() and not ring.closed:
                    chunk = synthetic_feed()
                    if chunk is None:
                        chunk = np.zeros((frame_n, native_ch), dtype=np.float32)
                    ring.write(np.asarray(chunk, dtype=np.float32))
                    next_t += interval
                    delay = next_t - time.perf_counter()
                    if delay > 0 and synth_stop.wait(timeout=delay):
                        break

            threading.Thread(target=_feed, name="snowlink-synth-audio", daemon=True).start()

        instance = cls(
            endpoint=endpoint,
            ring=ring,
            converter=converter,
            capture=capture_obj,
            _pa=pa_obj,
            _owns_pa=owns_pa,
            sample_rate=sample_rate,
            channels=channels,
            frame_ms=frame_ms,
            _synth_stop=synth_stop,
        )
        return instance

    def shutdown(self) -> None:
        if self._synth_stop is not None:
            self._synth_stop.set()
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                logger.debug("loopback stop failed", exc_info=True)
            try:
                self.capture.close()
            except Exception:
                logger.debug("loopback close failed", exc_info=True)
            self.capture = None
        try:
            self.ring.close()
        except Exception:
            pass
        if self._owns_pa and self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                logger.debug("PyAudio terminate failed", exc_info=True)
            self._pa = None


class LoopbackAudioTrack(AudioStreamTrack):
    """Custom AudioStreamTrack publishing converted WASAPI loopback frames."""

    kind = "audio"

    def __init__(
        self,
        source: ShareAudioCapture,
        *,
        read_chunk_frames: int | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.sample_rate = int(source.sample_rate)
        self.channels = int(source.channels)
        self.frame_ms = int(source.frame_ms)
        self.samples_per_frame = samples_per_frame(self.sample_rate, self.frame_ms)
        self._frame_duration_s = self.samples_per_frame / float(self.sample_rate)
        native_rate = int(source.converter.source_rate)
        self._read_chunk = int(
            read_chunk_frames
            if read_chunk_frames is not None
            else samples_per_frame(native_rate, self.frame_ms)
        )
        self._start_mono: float | None = None
        self._next_index = 0
        self._last_pts = -1
        self._frames_generated = 0
        self._silence_frames = 0
        self._underruns = 0
        self._late_events = 0
        self.peak_level = 0.0
        self._stopped = False
        self._stop_event = asyncio.Event()
        self._pending_frames: list[Any] = []

    @property
    def frames_generated(self) -> int:
        return self._frames_generated

    @property
    def silence_frames(self) -> int:
        return self._silence_frames

    @property
    def underruns(self) -> int:
        return self._underruns

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        super().stop()

    def _pull_one_frame(self) -> Any:
        """Blocking helper: convert ring PCM into one media AudioFrame or silence."""
        converter = self.source.converter
        ring = self.source.ring
        if self._pending_frames:
            return self._pending_frames.pop(0)

        # Drain available ring data (non-blocking) into the converter.
        pulled = False
        while True:
            data, underrun = ring.read_exact(self._read_chunk, timeout=0.0)
            if underrun and not pulled:
                break
            if underrun:
                break
            pulled = True
            produced = converter.push(data)
            if produced:
                self._pending_frames.extend(produced)
                return self._pending_frames.pop(0)

        # Brief wait for capture to catch up.
        data, underrun = ring.read_exact(self._read_chunk, timeout=0.005)
        if not underrun:
            produced = converter.push(data)
            if produced:
                self._pending_frames.extend(produced)
                return self._pending_frames.pop(0)

        self._underruns += 1
        return converter.make_silence_frame(underrun_padding=True)

    async def recv(self) -> Any:
        if self._stopped or self.source.ring.closed:
            raise MediaStreamError

        now = time.perf_counter()
        if self._start_mono is None:
            self._start_mono = now

        elapsed = now - self._start_mono
        self._next_index, late_delta, _lateness = schedule_audio_index(
            elapsed_s=elapsed,
            frame_duration_s=self._frame_duration_s,
            next_index=self._next_index,
        )
        if late_delta:
            self._late_events += 1

        target = self._start_mono + (self._next_index * self._frame_duration_s)
        delay = target - time.perf_counter()
        if delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            if self._stopped or self.source.ring.closed:
                raise MediaStreamError

        media_frame = await asyncio.to_thread(self._pull_one_frame)
        pcm = np.asarray(media_frame.samples)
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        if pcm.dtype != np.int16:
            from snowlink.media.audio_format import float32_to_s16

            pcm = float32_to_s16(pcm.astype(np.float32))
        try:
            peak = float(np.max(np.abs(pcm.astype(np.float32) / 32768.0)))
            if peak > self.peak_level:
                self.peak_level = peak
        except Exception:
            pass

        pts = int(media_frame.pts)
        if pts <= self._last_pts:
            pts = self._last_pts + self.samples_per_frame
        self._last_pts = pts

        frame = pcm_to_audio_frame(pcm, sample_rate=self.sample_rate, pts=pts)
        self._next_index += 1
        self._frames_generated += 1
        if media_frame.is_silence or media_frame.is_underrun_padding:
            self._silence_frames += 1
        return frame
