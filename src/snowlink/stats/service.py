"""Live session statistics for Share / View UI and CLI."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SessionStats:
    """Snapshot of capture / render / network counters (MVP stats panel)."""

    capture_fps: float | None = None
    render_fps: float | None = None
    width: int | None = None
    height: int | None = None
    estimated_bitrate_kbps: float | None = None
    rtt_ms: float | None = None
    packet_loss: float | None = None
    dropped_video_frames: int = 0
    audio_underruns: int = 0
    audio_peak: float | None = None
    av_skew_ms: float | None = None
    frames_sent: int | None = None
    frames_received: int | None = None
    ice_state: str | None = None
    cpu_percent: float | None = None
    rss_mb: float | None = None
    updated_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def format_lines(self, *, compact: bool = False) -> list[str]:
        """Human-readable lines for the stats panel.

        ``compact=True`` shows FPS, resolution, bitrate, and RTT only.
        """

        def _f(value: float | None, suffix: str = "", digits: int = 1) -> str:
            if value is None:
                return "—"
            return f"{value:.{digits}f}{suffix}"

        loss = "—" if self.packet_loss is None else f"{self.packet_loss * 100:.1f}%"
        res = "—"
        if self.width and self.height:
            res = f"{self.width}×{self.height}"
        peak = "—"
        if self.audio_peak is not None:
            # Show as percent of full scale for easier reading.
            peak = f"{min(100.0, self.audio_peak * 100.0):.0f}%"
        compact_lines = [
            f"Capture FPS: {_f(self.capture_fps)}",
            f"Render FPS: {_f(self.render_fps)}",
            f"Resolution: {res}",
            f"Bitrate: {_f(self.estimated_bitrate_kbps, ' kbps', 0)}",
            f"RTT: {_f(self.rtt_ms, ' ms', 0)}",
        ]
        if compact:
            return compact_lines
        return [
            *compact_lines,
            f"Packet loss: {loss}",
            f"Dropped video: {self.dropped_video_frames}",
            f"Audio underruns: {self.audio_underruns}",
            f"Audio level: {peak}",
            f"A/V skew: {_f(self.av_skew_ms, ' ms', 0)}",
            f"CPU: {_f(self.cpu_percent, '%', 0)}",
            f"RSS: {_f(self.rss_mb, ' MB', 0)}",
        ]


@dataclass
class StatsSampler:
    """Derive FPS / bitrate from counters + optional aiortc getStats reports."""

    width: int | None = None
    height: int | None = None
    _start_mono: float = field(default_factory=time.monotonic)
    _last_mono: float = field(default_factory=time.monotonic)
    _last_video_frames: int = 0
    _last_bytes: int = 0
    _capture_fps: float | None = None
    _render_fps: float | None = None
    _bitrate_kbps: float | None = None
    _rtt_ms: float | None = None
    _packet_loss: float | None = None
    _frames_sent: int | None = None
    _frames_received: int | None = None
    _av_skew_ms: float | None = None
    _audio_peak: float | None = None
    _cpu_percent: float | None = None
    _rss_mb: float | None = None
    _resource: Any = field(default=None, repr=False)

    def _ensure_resource_sampler(self) -> None:
        if self._resource is not None:
            return
        try:
            from snowlink.media.capture_metrics import ProcessResourceSampler

            self._resource = ProcessResourceSampler()
        except Exception:
            self._resource = False  # type: ignore[assignment]

    def sample_resources(self) -> None:
        """Refresh process CPU% and RSS when psutil is available."""
        self._ensure_resource_sampler()
        sampler = self._resource
        if not sampler or sampler is False:
            return
        try:
            sampler.sample()
            if sampler.cpu_samples:
                self._cpu_percent = float(sampler.cpu_samples[-1])
            rss = sampler._rss_mb()  # noqa: SLF001 — live panel needs current RSS
            if rss is not None:
                self._rss_mb = float(rss)
        except Exception:
            return

    def observe_local(
        self,
        *,
        video_frames: int,
        dropped_video_frames: int = 0,
        audio_underruns: int = 0,
        ice_state: str | None = None,
        role: str = "share",
        av_skew_ms: float | None = None,
        audio_peak: float | None = None,
    ) -> SessionStats:
        now = time.monotonic()
        dt = max(1e-3, now - self._last_mono)
        delta = max(0, video_frames - self._last_video_frames)
        fps = delta / dt
        if role == "share":
            self._capture_fps = fps
        else:
            self._render_fps = fps
        self._last_video_frames = video_frames
        self._last_mono = now
        if av_skew_ms is not None:
            self._av_skew_ms = av_skew_ms
        if audio_peak is not None:
            prev = self._audio_peak or 0.0
            self._audio_peak = max(prev, float(audio_peak))
        self.sample_resources()
        return SessionStats(
            capture_fps=self._capture_fps,
            render_fps=self._render_fps,
            width=self.width,
            height=self.height,
            estimated_bitrate_kbps=self._bitrate_kbps,
            rtt_ms=self._rtt_ms,
            packet_loss=self._packet_loss,
            dropped_video_frames=dropped_video_frames,
            audio_underruns=audio_underruns,
            audio_peak=self._audio_peak,
            av_skew_ms=self._av_skew_ms,
            frames_sent=self._frames_sent,
            frames_received=self._frames_received,
            ice_state=ice_state,
            cpu_percent=self._cpu_percent,
            rss_mb=self._rss_mb,
            updated_at=now,
        )

    def apply_rtc_report(self, report: Any) -> None:
        """Update network fields from ``pc.getStats()`` via parse_rtc_stats_report."""
        try:
            from snowlink.rtc.webrtc_metrics import parse_rtc_stats_report
        except Exception:
            return
        try:
            parsed = parse_rtc_stats_report(report)
        except Exception:
            return
        net = parsed.network
        video = parsed.video
        if net.current_rtt_ms is not None:
            self._rtt_ms = float(net.current_rtt_ms)
        if net.estimated_bitrate_bps is not None:
            self._bitrate_kbps = float(net.estimated_bitrate_bps) / 1000.0
        elif net.bytes_sent is not None or net.bytes_received is not None:
            now = time.monotonic()
            dt = max(1e-3, now - self._last_mono)
            total = int(net.bytes_sent or 0) + int(net.bytes_received or 0)
            delta_b = max(0, total - self._last_bytes)
            self._bitrate_kbps = (delta_b * 8.0) / dt / 1000.0
            self._last_bytes = total
        sent = net.packets_sent
        lost = net.packets_lost
        if sent is not None and lost is not None and (sent + lost) > 0:
            self._packet_loss = float(lost) / float(sent + lost)
        if video.frames_sent is not None:
            self._frames_sent = int(video.frames_sent)
        if video.frames_received is not None:
            self._frames_received = int(video.frames_received)
        if video.width:
            self.width = int(video.width)
        if video.height:
            self.height = int(video.height)
