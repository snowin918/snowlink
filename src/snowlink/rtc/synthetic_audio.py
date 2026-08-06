"""Synthetic aiortc AudioStreamTrack for Experiment F.

Canonical internal format
-------------------------
- sample format: s16
- layout: stereo (or mono when channels=1)
- sample rate: 48_000 Hz (configurable; default 48 kHz)
- frame samples per channel: 960 at 48 kHz / 20 ms
- audio RTP clock / time_base: 1/48000
- PTS: sample-driven — first frame PTS is 0; each ordinary frame advances by
  exactly samples_per_frame. Silence frames advance PTS normally. Wall-clock
  time is never used as PTS.
"""

from __future__ import annotations

import asyncio
import math
import time
from fractions import Fraction
from typing import Any, Literal

import numpy as np

from snowlink.media.audio_format import samples_per_frame
from snowlink.rtc.models import (
    AUDIO_CLOCK_RATE,
    DEFAULT_AUDIO_AMPLITUDE,
    DEFAULT_AUDIO_CHANNELS,
    DEFAULT_AUDIO_FRAME_MS,
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_PULSE_INTERVAL_MS,
    DEFAULT_TONE_FREQUENCY_HZ,
)

try:
    from av import AudioFrame
except ImportError as exc:  # pragma: no cover
    raise ImportError("PyAV (av) is required for synthetic audio") from exc

try:
    from aiortc import AudioStreamTrack
    from aiortc.mediastreams import MediaStreamError
except ImportError as exc:  # pragma: no cover
    raise ImportError("aiortc is required for synthetic audio") from exc

SignalType = Literal["sine", "silence", "pulse", "alternating"]

AUDIO_TIME_BASE = Fraction(1, AUDIO_CLOCK_RATE)


def generate_pcm_s16(
    *,
    signal: SignalType,
    sample_rate: int,
    channels: int,
    samples: int,
    sample_index: int,
    frequency_hz: float,
    amplitude: float,
    pulse_interval_ms: int,
) -> tuple[np.ndarray, bool]:
    """Generate interleaved s16 PCM shaped ``(samples, channels)``.

    Returns ``(pcm, is_silence)``.
    """
    if samples < 1:
        raise ValueError("samples must be >= 1")
    if channels < 1:
        raise ValueError("channels must be >= 1")
    amp = float(np.clip(amplitude, 0.0, 1.0))
    t = (sample_index + np.arange(samples, dtype=np.float64)) / float(sample_rate)

    if signal == "silence":
        mono = np.zeros(samples, dtype=np.float64)
        is_silence = True
    elif signal == "sine":
        mono = amp * np.sin(2.0 * math.pi * frequency_hz * t)
        is_silence = amp == 0.0
    elif signal == "pulse":
        interval_s = max(pulse_interval_ms, 1) / 1000.0
        pulse_width_s = min(0.005, interval_s / 4.0)
        phase = np.mod(t, interval_s)
        mono = np.where(phase < pulse_width_s, amp, 0.0)
        is_silence = bool(np.max(np.abs(mono)) < 1e-9)
    elif signal == "alternating":
        # 500 ms tone / 500 ms silence blocks.
        block = 0.5
        in_tone = (np.floor(t / block).astype(np.int64) % 2) == 0
        tone = amp * np.sin(2.0 * math.pi * frequency_hz * t)
        mono = np.where(in_tone, tone, 0.0)
        is_silence = not bool(np.any(in_tone)) or amp == 0.0
    else:
        raise ValueError(f"unknown signal type: {signal!r}")

    mono = np.clip(mono, -1.0, 1.0)
    s16 = (mono * 32767.0).astype(np.int16)
    if channels == 1:
        return s16.reshape(-1, 1), is_silence
    return np.repeat(s16.reshape(-1, 1), channels, axis=1), is_silence


def pcm_to_audio_frame(
    pcm: np.ndarray,
    *,
    sample_rate: int,
    pts: int,
    time_base: Fraction | None = None,
) -> Any:
    """Pack interleaved s16 PCM into a PyAV AudioFrame with sample-driven PTS."""
    if pcm.ndim != 2:
        raise ValueError("pcm must be shaped (samples, channels)")
    samples, channels = int(pcm.shape[0]), int(pcm.shape[1])
    layout = "stereo" if channels >= 2 else "mono"
    tb = time_base if time_base is not None else Fraction(1, sample_rate)
    frame = AudioFrame(format="s16", layout=layout, samples=samples)
    frame.sample_rate = sample_rate
    frame.pts = pts
    frame.time_base = tb
    interleaved = np.ascontiguousarray(pcm, dtype=np.int16)
    frame.planes[0].update(interleaved.tobytes())
    return frame


def compute_audio_pts_series(*, samples_per_frame: int, frame_count: int) -> list[int]:
    """Exact sample-driven PTS schedule (first PTS is 0)."""
    return [i * samples_per_frame for i in range(frame_count)]


def schedule_audio_index(
    *,
    elapsed_s: float,
    frame_duration_s: float,
    next_index: int,
) -> tuple[int, int, float]:
    """Return (new_next_index, late_events_delta, lateness_s) when catching up."""
    due = int(elapsed_s / frame_duration_s)
    if due > next_index:
        lateness = elapsed_s - (next_index * frame_duration_s)
        return due, due - next_index, max(0.0, lateness)
    return next_index, 0, 0.0


class SyntheticAudioTrack(AudioStreamTrack):
    """Custom AudioStreamTrack producing synthetic s16 Opus-ready frames."""

    kind = "audio"

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
        channels: int = DEFAULT_AUDIO_CHANNELS,
        frame_ms: int = DEFAULT_AUDIO_FRAME_MS,
        signal: SignalType = "sine",
        frequency_hz: float = DEFAULT_TONE_FREQUENCY_HZ,
        amplitude: float = DEFAULT_AUDIO_AMPLITUDE,
        pulse_interval_ms: int = DEFAULT_PULSE_INTERVAL_MS,
    ) -> None:
        super().__init__()
        if sample_rate < 1:
            raise ValueError("sample_rate must be >= 1")
        if channels not in {1, 2}:
            raise ValueError("channels must be 1 or 2")
        if frame_ms < 1:
            raise ValueError("frame_ms must be >= 1")
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frame_ms = int(frame_ms)
        self.signal: SignalType = signal
        self.frequency_hz = float(frequency_hz)
        self.amplitude = float(np.clip(amplitude, 0.0, 1.0))
        self.pulse_interval_ms = int(pulse_interval_ms)
        self.samples_per_frame = samples_per_frame(self.sample_rate, self.frame_ms)
        self.time_base = Fraction(1, self.sample_rate)
        self._frame_duration_s = self.samples_per_frame / float(self.sample_rate)
        self._start_mono: float | None = None
        self._next_index = 0
        self._sample_index = 0
        self._last_pts = -1
        self._frames_generated = 0
        self._samples_generated = 0
        self._silence_frames = 0
        self._late_events = 0
        self._max_lateness_s = 0.0
        self._stopped = False
        self._stop_event = asyncio.Event()

    @property
    def frames_generated(self) -> int:
        return self._frames_generated

    @property
    def samples_generated(self) -> int:
        return self._samples_generated

    @property
    def silence_frames(self) -> int:
        return self._silence_frames

    @property
    def late_generation_events(self) -> int:
        return self._late_events

    @property
    def max_generation_lateness_ms(self) -> float:
        return self._max_lateness_s * 1000.0

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        super().stop()

    async def recv(self) -> Any:
        if self._stopped:
            raise MediaStreamError

        now = time.perf_counter()
        if self._start_mono is None:
            self._start_mono = now

        elapsed = now - self._start_mono
        self._next_index, late_delta, lateness = schedule_audio_index(
            elapsed_s=elapsed,
            frame_duration_s=self._frame_duration_s,
            next_index=self._next_index,
        )
        if late_delta:
            self._late_events += 1
            self._max_lateness_s = max(self._max_lateness_s, lateness)
            # Preserve continuous sample timeline: jump sample_index with next_index.
            self._sample_index = self._next_index * self.samples_per_frame

        target = self._start_mono + (self._next_index * self._frame_duration_s)
        delay = target - time.perf_counter()
        if delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            if self._stopped:
                raise MediaStreamError

        now = time.perf_counter()
        assert self._start_mono is not None
        elapsed = now - self._start_mono
        self._next_index, late_delta, lateness = schedule_audio_index(
            elapsed_s=elapsed,
            frame_duration_s=self._frame_duration_s,
            next_index=self._next_index,
        )
        if late_delta:
            self._late_events += 1
            self._max_lateness_s = max(self._max_lateness_s, lateness)
            self._sample_index = self._next_index * self.samples_per_frame

        pts = self._next_index * self.samples_per_frame
        if pts <= self._last_pts:
            pts = self._last_pts + self.samples_per_frame
        self._last_pts = pts

        pcm, is_silence = generate_pcm_s16(
            signal=self.signal,
            sample_rate=self.sample_rate,
            channels=self.channels,
            samples=self.samples_per_frame,
            sample_index=self._sample_index,
            frequency_hz=self.frequency_hz,
            amplitude=self.amplitude,
            pulse_interval_ms=self.pulse_interval_ms,
        )
        frame = pcm_to_audio_frame(
            pcm,
            sample_rate=self.sample_rate,
            pts=pts,
            time_base=self.time_base,
        )

        self._sample_index += self.samples_per_frame
        self._next_index += 1
        self._frames_generated += 1
        self._samples_generated += self.samples_per_frame
        if is_silence:
            self._silence_frames += 1
        return frame
