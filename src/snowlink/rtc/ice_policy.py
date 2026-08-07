"""ICE host-candidate policy: prefer selected LAN IPv4, no STUN/TURN."""

from __future__ import annotations

import logging
import re
from typing import Any

from snowlink.rtc.ice_diagnostics import parse_candidate_sdp

logger = logging.getLogger(__name__)

# Non-trickle MVP: peers gather ICE to completion and embed candidates in SDP.
# Trickle ``ice_candidate`` signaling messages are accepted by the schema but
# ignored by the signaling server (intentional for MVP stability).
TRICKLE_ICE_ENABLED = False

_CANDIDATE_LINE_RE = re.compile(r"^a=candidate:.*$", re.IGNORECASE | re.MULTILINE)
_END_OF_CANDIDATES_RE = re.compile(
    r"^a=end-of-candidates\s*$", re.IGNORECASE | re.MULTILINE
)


def prefer_selected_host_ip(sdp: str, selected_ip: str | None) -> str:
    """Filter SDP host candidates to prefer *selected_ip*.

    Keeps all non-host candidates (none expected in host-only MVP) and host
    candidates whose IP matches *selected_ip*. If filtering would remove every
    host candidate, the original SDP is returned unchanged.
    """
    if not selected_ip or not sdp:
        return sdp

    kept: list[str] = []
    removed = 0
    host_kept = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed, host_kept
        line = match.group(0)
        info = parse_candidate_sdp(line)
        cand_type = (info.type or "").lower()
        if cand_type and cand_type != "host":
            # Host-only MVP: drop srflx/relay if somehow present.
            removed += 1
            return ""
        if info.ip and info.ip != selected_ip:
            removed += 1
            return ""
        host_kept += 1
        kept.append(line)
        return line

    filtered = _CANDIDATE_LINE_RE.sub(_replace, sdp)
    # Collapse blank lines left by removals
    filtered = re.sub(r"\n{3,}", "\n\n", filtered)

    if host_kept == 0 and removed > 0:
        logger.warning(
            "ICE filter would remove all host candidates for %s; leaving SDP unchanged",
            selected_ip,
        )
        return sdp

    if removed:
        logger.info(
            "ICE host filter: kept=%d removed=%d preferred_ip=%s",
            host_kept,
            removed,
            selected_ip,
        )
    return filtered


def apply_ice_policy_to_local_description(pc: Any, selected_ip: str | None) -> None:
    """Munge ``pc.localDescription.sdp`` in place when a selected IP is known."""
    if pc is None or not selected_ip:
        return
    local = getattr(pc, "localDescription", None)
    if local is None or not getattr(local, "sdp", None):
        return
    new_sdp = prefer_selected_host_ip(str(local.sdp), selected_ip)
    if new_sdp == local.sdp:
        return
    try:
        from aiortc import RTCSessionDescription

        pc._localDescription = RTCSessionDescription(  # noqa: SLF001 — policy munge
            sdp=new_sdp,
            type=local.type,
        )
    except Exception:
        logger.exception("Failed to apply ICE host filter to local description")
