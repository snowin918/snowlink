"""Tone verification and audio metric helpers for Experiment F."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from snowlink.media.audio_format import is_silent_frame, peak_level, rms_level


@dataclass(slots=True)
class ToneVerificationStats:
    rms_average: float | None = None
    peak: float | None = None
    clipping_count: int = 0
    silent_frame_count: int = 0
    estimated_frequency_hz: float | None = None
    frames_analyzed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PulseVerificationStats:
    pulses_expected: int | None = None
    pulses_detected: int = 0
    pulses_missing: int = 0
    pulses_duplicate: int = 0
    pulse_interval_variation_ms: float | None = None
    arrival_intervals_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep intervals out of default result serialization noise.
        data.pop("arrival_intervals_ms", None)
        return data


def count_clipping(frames: NDArray[Any], *, threshold: float = 0.99) -> int:
    """Count samples at or above *threshold* (absolute float amplitude)."""
    arr = np.asarray(frames, dtype=np.float32)
    if arr.size == 0:
        return 0
    return int(np.sum(np.abs(arr) >= threshold))


def estimate_dominant_frequency_hz(
    frames: NDArray[Any],
    *,
    sample_rate: int,
    min_hz: float = 20.0,
    max_hz: float | None = None,
) -> float | None:
    """Estimate dominant frequency via FFT peak (mono mixdown).

    Tolerant of codec lossy artifacts; returns None when energy is too low.
    """
    arr = np.asarray(frames, dtype=np.float32)
    if arr.ndim == 2:
        mono = np.mean(arr, axis=1)
    else:
        mono = arr.reshape(-1)
    if mono.size < 32:
        return None
    # Remove DC.
    mono = mono - float(np.mean(mono))
    if float(np.max(np.abs(mono))) < 1e-5:
        return None
    window = np.hanning(mono.size).astype(np.float32)
    spectrum = np.fft.rfft(mono * window)
    mags = np.abs(spectrum)
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / float(sample_rate))
    hi = float(sample_rate) / 2.0 if max_hz is None else float(max_hz)
    mask = (freqs >= min_hz) & (freqs <= hi)
    if not np.any(mask):
        return None
    masked = np.where(mask, mags, 0.0)
    peak_i = int(np.argmax(masked))
    if masked[peak_i] <= 0:
        return None
    return float(freqs[peak_i])


def estimate_frequency_zero_crossing(
    frames: NDArray[Any],
    *,
    sample_rate: int,
) -> float | None:
    """Rough frequency estimate from zero crossings (fallback)."""
    arr = np.asarray(frames, dtype=np.float32)
    if arr.ndim == 2:
        mono = np.mean(arr, axis=1)
    else:
        mono = arr.reshape(-1)
    if mono.size < 4:
        return None
    signs = np.sign(mono)
    signs[signs == 0] = 1
    crossings = int(np.sum(signs[:-1] * signs[1:] < 0))
    if crossings < 2:
        return None
    duration_s = mono.size / float(sample_rate)
    return (crossings / 2.0) / duration_s


class ToneAnalyzer:
    """Accumulate RMS/peak/frequency estimates across received float frames."""

    def __init__(
        self,
        *,
        sample_rate: int,
        expected_frequency_hz: float | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.expected_frequency_hz = expected_frequency_hz
        self._rms_sum = 0.0
        self._rms_n = 0
        self._peak = 0.0
        self.clipping_count = 0
        self.silent_frame_count = 0
        self.frames_analyzed = 0
        self._freq_samples: list[float] = []
        self._pcm_accum = np.zeros(0, dtype=np.float32)
        self._accum_target = max(sample_rate // 4, 2048)  # ~250 ms for FFT

    def observe(self, frames: NDArray[Any]) -> None:
        arr = np.asarray(frames, dtype=np.float32)
        if arr.size == 0:
            return
        self.frames_analyzed += 1
        rms = rms_level(arr)
        peak = peak_level(arr)
        self._rms_sum += rms
        self._rms_n += 1
        self._peak = max(self._peak, peak)
        self.clipping_count += count_clipping(arr)
        if is_silent_frame(arr):
            self.silent_frame_count += 1
            return
        mono = np.mean(arr, axis=1) if arr.ndim == 2 else arr.reshape(-1)
        self._pcm_accum = np.concatenate([self._pcm_accum, mono.astype(np.float32)])
        while self._pcm_accum.size >= self._accum_target:
            chunk = self._pcm_accum[: self._accum_target]
            self._pcm_accum = self._pcm_accum[self._accum_target :]
            est = estimate_dominant_frequency_hz(
                chunk,
                sample_rate=self.sample_rate,
            )
            if est is None:
                est = estimate_frequency_zero_crossing(chunk, sample_rate=self.sample_rate)
            if est is not None:
                self._freq_samples.append(est)

    def finalize(self) -> ToneVerificationStats:
        if self._pcm_accum.size >= 64:
            est = estimate_dominant_frequency_hz(
                self._pcm_accum,
                sample_rate=self.sample_rate,
            )
            if est is None:
                est = estimate_frequency_zero_crossing(
                    self._pcm_accum,
                    sample_rate=self.sample_rate,
                )
            if est is not None:
                self._freq_samples.append(est)
        freq: float | None = None
        if self._freq_samples:
            # Prefer median for robustness against startup/transient estimates.
            freq = float(np.median(np.asarray(self._freq_samples, dtype=np.float64)))
        return ToneVerificationStats(
            rms_average=(self._rms_sum / self._rms_n) if self._rms_n else None,
            peak=self._peak if self._rms_n else None,
            clipping_count=self.clipping_count,
            silent_frame_count=self.silent_frame_count,
            estimated_frequency_hz=freq,
            frames_analyzed=self.frames_analyzed,
        )


class PulseDetector:
    """Detect periodic amplitude pulses for optional diagnostic pulse mode."""

    def __init__(
        self,
        *,
        sample_rate: int,
        pulse_interval_ms: int,
        amplitude_threshold: float = 0.05,
        duration_s: float | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.pulse_interval_ms = int(pulse_interval_ms)
        self.amplitude_threshold = float(amplitude_threshold)
        self.duration_s = duration_s
        self.pulses_detected = 0
        self.pulses_duplicate = 0
        self._last_pulse_sample: int | None = None
        self._sample_cursor = 0
        self._intervals_ms: list[float] = []
        self._in_pulse = False

    def observe(self, frames: NDArray[Any]) -> None:
        arr = np.asarray(frames, dtype=np.float32)
        if arr.ndim == 2:
            mono = np.mean(arr, axis=1)
        else:
            mono = arr.reshape(-1)
        for sample in mono:
            level = abs(float(sample))
            if level >= self.amplitude_threshold:
                if not self._in_pulse:
                    self._on_pulse_start(self._sample_cursor)
                    self._in_pulse = True
            else:
                self._in_pulse = False
            self._sample_cursor += 1

    def _on_pulse_start(self, sample_index: int) -> None:
        min_gap = max(1, int(self.sample_rate * self.pulse_interval_ms / 1000.0 * 0.4))
        if self._last_pulse_sample is not None:
            gap = sample_index - self._last_pulse_sample
            if gap < min_gap:
                self.pulses_duplicate += 1
                return
            self._intervals_ms.append(gap * 1000.0 / float(self.sample_rate))
        self._last_pulse_sample = sample_index
        self.pulses_detected += 1

    def finalize(self) -> PulseVerificationStats:
        expected: int | None = None
        if self.duration_s is not None and self.pulse_interval_ms > 0:
            expected = max(0, int(self.duration_s * 1000.0 / self.pulse_interval_ms))
        missing = 0
        if expected is not None:
            missing = max(0, expected - self.pulses_detected)
        variation: float | None = None
        if len(self._intervals_ms) >= 2:
            variation = float(np.std(np.asarray(self._intervals_ms, dtype=np.float64)))
        return PulseVerificationStats(
            pulses_expected=expected,
            pulses_detected=self.pulses_detected,
            pulses_missing=missing,
            pulses_duplicate=self.pulses_duplicate,
            pulse_interval_variation_ms=variation,
            arrival_intervals_ms=list(self._intervals_ms),
        )


@dataclass(slots=True)
class PtsValidator:
    """Track PTS continuity for received audio frames."""

    expected_step: int
    last_pts: int | None = None
    invalid_pts_count: int = 0
    missing_pts_count: int = 0
    frames_checked: int = 0

    def observe(self, pts: int | None) -> None:
        self.frames_checked += 1
        if pts is None:
            self.missing_pts_count += 1
            self.invalid_pts_count += 1
            return
        if self.last_pts is None:
            self.last_pts = int(pts)
            return
        delta = int(pts) - self.last_pts
        if delta <= 0:
            self.invalid_pts_count += 1
        elif self.expected_step > 0 and delta != self.expected_step:
            # Gaps are tolerable (packet loss / jitter); count missing steps when aligned.
            if delta % self.expected_step == 0:
                self.missing_pts_count += (delta // self.expected_step) - 1
        self.last_pts = int(pts)
