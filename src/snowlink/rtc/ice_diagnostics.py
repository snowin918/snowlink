"""ICE candidate parsing and adapter classification for Experiment E."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from typing import Any

from snowlink.net.adapter_models import NetworkAdapter
from snowlink.net.adapter_selection import annotate_adapters
from snowlink.rtc.models import CandidatePairInfo, IceCandidateInfo

# candidate:<foundation> <component> <protocol> <priority> <ip> <port> typ <type> ...
_CANDIDATE_RE = re.compile(
    r"candidate:(?P<foundation>\S+)\s+"
    r"(?P<component>\d+)\s+"
    r"(?P<protocol>\S+)\s+"
    r"(?P<priority>\d+)\s+"
    r"(?P<ip>\S+)\s+"
    r"(?P<port>\d+)\s+"
    r"typ\s+(?P<type>\S+)"
    r"(?:.*? raddr\s+(?P<raddr>\S+))?"
    r"(?:.*? rport\s+(?P<rport>\d+))?",
    re.IGNORECASE,
)


def parse_candidate_sdp(candidate: str) -> IceCandidateInfo:
    """Parse an ICE candidate attribute line into :class:`IceCandidateInfo`."""
    text = candidate.strip()
    if text.lower().startswith("a="):
        text = text[2:].strip()
    match = _CANDIDATE_RE.search(text)
    if not match:
        return IceCandidateInfo(raw=candidate)
    rport = match.group("rport")
    return IceCandidateInfo(
        ip=match.group("ip"),
        port=int(match.group("port")),
        protocol=match.group("protocol").lower(),
        type=match.group("type").lower(),
        foundation=match.group("foundation"),
        priority=int(match.group("priority")),
        related_address=match.group("raddr"),
        related_port=int(rport) if rport else None,
        raw=candidate,
    )


def classify_candidate_ip(
    ip: str | None,
    adapters: Sequence[NetworkAdapter],
) -> str | None:
    """Return adapter category for *ip*, or None when unknown / not local."""
    if not ip:
        return None
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    annotated = annotate_adapters(adapters)
    for adapter in annotated:
        for addr in adapter.ipv4_addresses:
            if addr.address == ip:
                return adapter.category.value
    if ip in {"127.0.0.1", "0.0.0.0"}:
        return "loopback"
    return None


def enrich_candidate(
    info: IceCandidateInfo,
    adapters: Sequence[NetworkAdapter],
) -> IceCandidateInfo:
    """Attach adapter_category when the candidate IP matches a local adapter."""
    category = classify_candidate_ip(info.ip, adapters)
    info.adapter_category = category
    return info


def serialize_candidates(candidates: Sequence[IceCandidateInfo]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in candidates]


def selected_matches_requested_ip(
    selected_local: IceCandidateInfo | None,
    requested_ip: str | None,
) -> bool | None:
    """True/False when both sides known; None when comparison is not applicable."""
    if not requested_ip or selected_local is None or not selected_local.ip:
        return None
    return selected_local.ip == requested_ip


def mismatch_warning(
    selected_local: IceCandidateInfo | None,
    requested_ip: str | None,
) -> str | None:
    """Human-readable warning when ICE picked a different local IP."""
    match = selected_matches_requested_ip(selected_local, requested_ip)
    if match is False and selected_local is not None and requested_ip:
        category = selected_local.adapter_category or "unknown"
        return (
            f"ICE_SELECTED_WRONG_INTERFACE: selected local candidate "
            f"{selected_local.ip} ({category}) != requested {requested_ip}"
        )
    return None


def candidate_from_aiortc(obj: Any, adapters: Sequence[NetworkAdapter]) -> IceCandidateInfo:
    """Best-effort conversion from an aiortc / aioice candidate object."""
    if obj is None:
        return IceCandidateInfo()
    # RTCIceCandidate-like
    cand_str = getattr(obj, "candidate", None)
    if isinstance(cand_str, str) and cand_str:
        info = parse_candidate_sdp(cand_str)
        return enrich_candidate(info, adapters)
    ip = getattr(obj, "ip", None) or getattr(obj, "address", None) or getattr(obj, "host", None)
    port = getattr(obj, "port", None)
    protocol = getattr(obj, "protocol", None)
    typ = getattr(obj, "type", None) or getattr(obj, "candidateType", None)
    info = IceCandidateInfo(
        ip=str(ip) if ip else None,
        port=int(port) if port is not None else None,
        protocol=str(protocol).lower() if protocol else None,
        type=str(typ).lower() if typ else None,
        foundation=str(getattr(obj, "foundation", "") or None),
        priority=int(getattr(obj, "priority")) if getattr(obj, "priority", None) else None,
    )
    return enrich_candidate(info, adapters)


def pair_from_stats(
    *,
    local: IceCandidateInfo | None,
    remote: IceCandidateInfo | None,
    state: str | None = None,
    nominated: bool | None = None,
    current_rtt_ms: float | None = None,
    available_outgoing_bitrate: float | None = None,
    bytes_sent: int | None = None,
    bytes_received: int | None = None,
    packets_sent: int | None = None,
    packets_received: int | None = None,
) -> CandidatePairInfo:
    return CandidatePairInfo(
        local=local,
        remote=remote,
        state=state,
        nominated=nominated,
        current_rtt_ms=current_rtt_ms,
        available_outgoing_bitrate=available_outgoing_bitrate,
        bytes_sent=bytes_sent,
        bytes_received=bytes_received,
        packets_sent=packets_sent,
        packets_received=packets_received,
    )


class CandidateFilter:
    """Experiment-only abstraction for optional candidate filtering.

    Default policy: do not filter. Documented private-API hooks may be added later;
    this experiment records all host candidates rather than mutating SDP by default.
    """

    def filter_local_candidates(
        self,
        candidates: Sequence[IceCandidateInfo],
        *,
        preferred_ip: str | None = None,
    ) -> list[IceCandidateInfo]:
        _ = preferred_ip
        return list(candidates)
