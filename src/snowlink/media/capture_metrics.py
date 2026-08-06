"""Metrics helpers for Experiment C capture benchmarks."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from snowlink.media.capture_models import ResourceStats, TimingStatsMs


def percentile(samples: list[float], pct: float) -> float | None:
    """Nearest-rank percentile for *pct* in [0, 100].

    Uses a sorted copy; returns None when *samples* is empty.
    """
    if not samples:
        return None
    if pct <= 0:
        return float(min(samples))
    if pct >= 100:
        return float(max(samples))
    ordered = sorted(samples)
    # Nearest-rank: rank = ceil(p/100 * N), 1-indexed
    rank = max(1, int((pct / 100.0) * len(ordered) + 0.999999999))
    index = min(len(ordered), rank) - 1
    return float(ordered[index])


def average(samples: list[float]) -> float | None:
    if not samples:
        return None
    return float(statistics.fmean(samples))


@dataclass(slots=True)
class TimingAccumulator:
    """Collect high-resolution duration samples (stored as milliseconds)."""

    capture_intervals_ms: list[float] = field(default_factory=list)
    frame_ages_ms: list[float] = field(default_factory=list)
    scale_times_ms: list[float] = field(default_factory=list)
    capture_to_preview_ms: list[float] = field(default_factory=list)

    def add_capture_interval_ns(self, interval_ns: int) -> None:
        if interval_ns >= 0:
            self.capture_intervals_ms.append(interval_ns / 1_000_000.0)

    def add_frame_age_ns(self, age_ns: int) -> None:
        if age_ns >= 0:
            self.frame_ages_ms.append(age_ns / 1_000_000.0)

    def add_scale_ns(self, scale_ns: int) -> None:
        if scale_ns >= 0:
            self.scale_times_ms.append(scale_ns / 1_000_000.0)

    def add_capture_to_preview_ns(self, delay_ns: int) -> None:
        if delay_ns >= 0:
            self.capture_to_preview_ms.append(delay_ns / 1_000_000.0)

    def to_timing_stats(self) -> TimingStatsMs:
        return TimingStatsMs(
            capture_interval_average=average(self.capture_intervals_ms),
            capture_interval_p50=percentile(self.capture_intervals_ms, 50),
            capture_interval_p95=percentile(self.capture_intervals_ms, 95),
            capture_interval_p99=percentile(self.capture_intervals_ms, 99),
            frame_age_average=average(self.frame_ages_ms),
            frame_age_p50=percentile(self.frame_ages_ms, 50),
            frame_age_p95=percentile(self.frame_ages_ms, 95),
            frame_age_p99=percentile(self.frame_ages_ms, 99),
            scale_average=average(self.scale_times_ms),
            scale_p50=percentile(self.scale_times_ms, 50),
            scale_p95=percentile(self.scale_times_ms, 95),
            capture_to_preview_average=average(self.capture_to_preview_ms),
            capture_to_preview_p95=percentile(self.capture_to_preview_ms, 95),
        )


class ProcessResourceSampler:
    """Sample process CPU% and RSS via psutil when available."""

    def __init__(self) -> None:
        self._process: Any | None = None
        self._available = False
        self.cpu_samples: list[float] = []
        self.memory_mb_start: float | None = None
        self.memory_mb_end: float | None = None
        self.memory_mb_peak: float | None = None
        try:
            import psutil  # type: ignore[import-untyped]

            self._process = psutil.Process()
            # First cpu_percent call is a baseline (often 0.0).
            self._process.cpu_percent(interval=None)
            self._available = True
            self.memory_mb_start = self._rss_mb()
            self.memory_mb_peak = self.memory_mb_start
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _rss_mb(self) -> float | None:
        if self._process is None:
            return None
        try:
            return float(self._process.memory_info().rss) / (1024.0 * 1024.0)
        except Exception:
            return None

    def sample(self) -> None:
        if not self._available or self._process is None:
            return
        try:
            cpu = float(self._process.cpu_percent(interval=None))
            self.cpu_samples.append(cpu)
            mem = self._rss_mb()
            if mem is not None:
                if self.memory_mb_peak is None or mem > self.memory_mb_peak:
                    self.memory_mb_peak = mem
                self.memory_mb_end = mem
        except Exception:
            return

    def finalize(self) -> ResourceStats:
        self.sample()
        if self.memory_mb_end is None:
            self.memory_mb_end = self._rss_mb()
        return ResourceStats(
            cpu_percent_average=average(self.cpu_samples),
            cpu_percent_peak=max(self.cpu_samples) if self.cpu_samples else None,
            memory_mb_start=self.memory_mb_start,
            memory_mb_end=self.memory_mb_end,
            memory_mb_peak=self.memory_mb_peak,
        )


def elapsed_s(start_ns: int, end_ns: int | None = None) -> float:
    end = time.perf_counter_ns() if end_ns is None else end_ns
    return max(0.0, (end - start_ns) / 1_000_000_000.0)
