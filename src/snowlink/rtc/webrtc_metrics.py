"""WebRTC metrics helpers for Experiment E."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from snowlink.rtc.models import NetworkStats, ResourceStats, VideoStats


def percentile(samples: list[float], pct: float) -> float | None:
    if not samples:
        return None
    if pct <= 0:
        return float(min(samples))
    if pct >= 100:
        return float(max(samples))
    ordered = sorted(samples)
    rank = max(1, int((pct / 100.0) * len(ordered) + 0.999999999))
    index = min(len(ordered), rank) - 1
    return float(ordered[index])


def average(samples: list[float]) -> float | None:
    if not samples:
        return None
    return float(statistics.fmean(samples))


@dataclass(slots=True)
class SequenceTracker:
    """Track duplicate / missing / out-of-order synthetic frame sequence numbers."""

    seen: set[int] = field(default_factory=set)
    last_sequence: int | None = None
    duplicate_sequences: int = 0
    missing_sequences: int = 0
    out_of_order_sequences: int = 0
    frames_received: int = 0

    def observe(self, sequence: int) -> None:
        self.frames_received += 1
        if sequence in self.seen:
            self.duplicate_sequences += 1
        else:
            self.seen.add(sequence)
            if self.last_sequence is not None and sequence > self.last_sequence + 1:
                self.missing_sequences += sequence - self.last_sequence - 1
        if self.last_sequence is not None and sequence < self.last_sequence:
            self.out_of_order_sequences += 1
        if self.last_sequence is None or sequence > self.last_sequence:
            self.last_sequence = sequence


@dataclass(slots=True)
class InterArrivalTracker:
    intervals_ms: list[float] = field(default_factory=list)
    _last_recv_ns: int | None = None

    def observe_now(self) -> None:
        now = time.perf_counter_ns()
        if self._last_recv_ns is not None:
            self.intervals_ms.append((now - self._last_recv_ns) / 1_000_000.0)
        self._last_recv_ns = now

    def average_ms(self) -> float | None:
        return average(self.intervals_ms)

    def p95_ms(self) -> float | None:
        return percentile(self.intervals_ms, 95)


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
            self._process.cpu_percent(interval=None)
            self._available = True
            self.memory_mb_start = self._rss_mb()
            self.memory_mb_peak = self.memory_mb_start
        except Exception:
            self._available = False

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
                self.memory_mb_peak = (
                    mem if self.memory_mb_peak is None else max(self.memory_mb_peak, mem)
                )
        except Exception:
            return

    def finalize(self) -> ResourceStats:
        self.memory_mb_end = self._rss_mb()
        if self.memory_mb_end is not None:
            self.memory_mb_peak = (
                self.memory_mb_end
                if self.memory_mb_peak is None
                else max(self.memory_mb_peak, self.memory_mb_end)
            )
        return ResourceStats(
            cpu_percent_average=average(self.cpu_samples),
            cpu_percent_peak=max(self.cpu_samples) if self.cpu_samples else None,
            memory_mb_start=self.memory_mb_start,
            memory_mb_end=self.memory_mb_end,
            memory_mb_peak=self.memory_mb_peak,
        )


def _stat_get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ParsedRtcStats:
    network: NetworkStats
    video: VideoStats
    codec_name: str | None = None
    codec_payload_type: int | None = None
    selected_pair_id: str | None = None
    local_candidate_id: str | None = None
    remote_candidate_id: str | None = None
    raw_candidates: list[Any] = field(default_factory=list)
    raw_pairs: list[Any] = field(default_factory=list)


def parse_rtc_stats_report(report: Any) -> ParsedRtcStats:
    """Extract optional metrics from an aiortc getStats() report.

    Missing fields are left as None — never raises merely because a metric is absent.
    """
    network = NetworkStats()
    video = VideoStats()
    items: list[Any]
    if report is None:
        return ParsedRtcStats(network=network, video=video)
    if isinstance(report, dict):
        items = list(report.values())
    else:
        try:
            items = list(report.values())
        except Exception:
            try:
                items = list(report)
            except Exception:
                items = []

    codec_name: str | None = None
    codec_payload_type: int | None = None
    selected_pair_id: str | None = None
    local_candidate_id: str | None = None
    remote_candidate_id: str | None = None
    raw_candidates: list[Any] = []
    raw_pairs: list[Any] = []

    by_id: dict[str, Any] = {}
    for item in items:
        item_id = _stat_get(item, "id")
        if item_id is not None:
            by_id[str(item_id)] = item

    for item in items:
        typ = str(_stat_get(item, "type") or "").lower()
        if typ in {"outbound-rtp", "outboundrtp"}:
            network.bytes_sent = _as_int(_stat_get(item, "bytesSent", "bytes_sent"))
            network.packets_sent = _as_int(_stat_get(item, "packetsSent", "packets_sent"))
            video.frames_encoded = _as_int(
                _stat_get(item, "framesEncoded", "frames_encoded")
            )
            video.frames_sent = _as_int(_stat_get(item, "framesSent", "frames_sent"))
            video.key_frames = _as_int(_stat_get(item, "keyFramesEncoded", "key_frames"))
            video.width = _as_int(_stat_get(item, "frameWidth", "frame_width")) or video.width
            video.height = _as_int(_stat_get(item, "frameHeight", "frame_height")) or video.height
            br = _as_float(_stat_get(item, "targetBitrate", "bytesSent"))
            if br is not None and _stat_get(item, "targetBitrate") is not None:
                network.estimated_bitrate_bps = br
        elif typ in {"inbound-rtp", "inboundrtp"}:
            network.bytes_received = _as_int(
                _stat_get(item, "bytesReceived", "bytes_received")
            )
            network.packets_received = _as_int(
                _stat_get(item, "packetsReceived", "packets_received")
            )
            network.packets_lost = _as_int(_stat_get(item, "packetsLost", "packets_lost"))
            jitter = _as_float(_stat_get(item, "jitter"))
            if jitter is not None:
                # WebRTC jitter is in seconds for RTP; convert to ms when small.
                network.jitter_ms = jitter * 1000.0 if jitter < 10 else jitter
            video.frames_decoded = _as_int(
                _stat_get(item, "framesDecoded", "frames_decoded")
            )
            video.frames_received = int(
                _as_int(_stat_get(item, "framesReceived", "frames_received"))
                or video.frames_received
            )
            video.frames_dropped = _as_int(
                _stat_get(item, "framesDropped", "frames_dropped")
            )
            video.width = _as_int(_stat_get(item, "frameWidth", "frame_width")) or video.width
            video.height = _as_int(_stat_get(item, "frameHeight", "frame_height")) or video.height
        elif typ in {"remote-inbound-rtp", "remoteinboundrtp"}:
            rtt = _as_float(_stat_get(item, "roundTripTime", "totalRoundTripTime"))
            if rtt is not None:
                network.current_rtt_ms = rtt * 1000.0 if rtt < 10 else rtt
            network.remote_inbound_packets_lost = _as_int(
                _stat_get(item, "packetsLost", "packets_lost")
            )
        elif typ in {"candidate-pair", "candidatepair"}:
            raw_pairs.append(item)
            state = str(_stat_get(item, "state") or "").lower()
            nominated = _stat_get(item, "nominated")
            selected = _stat_get(item, "selected")
            if selected or nominated or state == "succeeded":
                selected_pair_id = str(_stat_get(item, "id") or selected_pair_id or "")
                local_candidate_id = str(
                    _stat_get(item, "localCandidateId", "local_candidate_id") or ""
                )
                remote_candidate_id = str(
                    _stat_get(item, "remoteCandidateId", "remote_candidate_id") or ""
                )
                rtt = _as_float(_stat_get(item, "currentRoundTripTime", "current_rtt"))
                if rtt is not None:
                    network.current_rtt_ms = rtt * 1000.0 if rtt < 10 else rtt
                br = _as_float(
                    _stat_get(item, "availableOutgoingBitrate", "available_outgoing_bitrate")
                )
                if br is not None:
                    network.estimated_bitrate_bps = br
                network.bytes_sent = (
                    _as_int(_stat_get(item, "bytesSent", "bytes_sent")) or network.bytes_sent
                )
                network.bytes_received = (
                    _as_int(_stat_get(item, "bytesReceived", "bytes_received"))
                    or network.bytes_received
                )
        elif typ in {"local-candidate", "localcandidate", "remote-candidate", "remotecandidate"}:
            raw_candidates.append(item)
        elif typ == "codec":
            mime = _stat_get(item, "mimeType", "mime_type")
            if mime:
                codec_name = str(mime)
            codec_payload_type = _as_int(_stat_get(item, "payloadType", "payload_type"))

    if codec_name:
        video.codec = codec_name
        video.codec_payload_type = codec_payload_type

    return ParsedRtcStats(
        network=network,
        video=video,
        codec_name=codec_name,
        codec_payload_type=codec_payload_type,
        selected_pair_id=selected_pair_id,
        local_candidate_id=local_candidate_id or None,
        remote_candidate_id=remote_candidate_id or None,
        raw_candidates=raw_candidates,
        raw_pairs=raw_pairs,
    )


def estimate_clock_offset_ms(
    samples: list[tuple[float, float, float, float]],
) -> tuple[float | None, float | None]:
    """NTP-style midpoint clock-offset estimate from ping/pong timestamps.

    Each sample is (t0, t1, t2, t3) where:
      t0 = client send (client clock)
      t1 = server receive (server clock)
      t2 = server send (server clock)
      t3 = client receive (client clock)

    Returns (offset_ms, uncertainty_ms) where offset approximates server - client.
    """
    if not samples:
        return None, None
    offsets: list[float] = []
    rtts: list[float] = []
    for t0, t1, t2, t3 in samples:
        rtt = (t3 - t0) - (t2 - t1)
        offset = ((t1 - t0) + (t2 - t3)) / 2.0
        offsets.append(offset * 1000.0)
        rtts.append(max(0.0, rtt) * 1000.0)
    offset_ms = average(offsets)
    uncertainty_ms = average(rtts)
    if uncertainty_ms is not None:
        uncertainty_ms = uncertainty_ms / 2.0
    return offset_ms, uncertainty_ms


def fps_from_count(count: int, elapsed_s: float) -> float | None:
    if elapsed_s <= 0:
        return None
    return float(count) / elapsed_s
