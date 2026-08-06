"""Metrics helpers for Experiment D audio benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field

from snowlink.media.audio_models import AudioTimingStatsMs
from snowlink.media.capture_metrics import average, percentile


@dataclass(slots=True)
class AudioTimingAccumulator:
    """Collect processing and local queue-delay samples (milliseconds)."""

    processing_ms: list[float] = field(default_factory=list)
    queue_delay_ms: list[float] = field(default_factory=list)
    fill_ms_samples: list[float] = field(default_factory=list)

    def add_processing_ns(self, duration_ns: int) -> None:
        if duration_ns >= 0:
            self.processing_ms.append(duration_ns / 1_000_000.0)

    def add_queue_delay_ms(self, delay_ms: float) -> None:
        if delay_ms >= 0:
            self.queue_delay_ms.append(float(delay_ms))

    def add_fill_ms(self, fill_ms: float) -> None:
        if fill_ms >= 0:
            self.fill_ms_samples.append(float(fill_ms))

    def to_timing_stats(self) -> AudioTimingStatsMs:
        return AudioTimingStatsMs(
            processing_average=average(self.processing_ms),
            processing_p50=percentile(self.processing_ms, 50),
            processing_p95=percentile(self.processing_ms, 95),
            queue_delay_average=average(self.queue_delay_ms),
            queue_delay_p50=percentile(self.queue_delay_ms, 50),
            queue_delay_p95=percentile(self.queue_delay_ms, 95),
        )

    def average_fill_ms(self) -> float | None:
        return average(self.fill_ms_samples)

    def peak_fill_ms(self) -> float | None:
        if not self.fill_ms_samples:
            return None
        return float(max(self.fill_ms_samples))
