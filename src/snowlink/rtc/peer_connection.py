"""aiortc peer-connection helpers for Experiment E (host ICE, VP8 preference)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snowlink.rtc.errors import WebRTCError, failure_for
from snowlink.rtc.models import AvailableCodec


def require_aiortc() -> None:
    try:
        import aiortc  # noqa: F401
    except ImportError as exc:
        raise WebRTCError(
            failure_for("AIORTC_NOT_INSTALLED", "aiortc is not installed.", exception=exc)
        ) from exc
    try:
        import av  # noqa: F401
    except ImportError as exc:
        raise WebRTCError(
            failure_for("PYAV_NOT_INSTALLED", "PyAV (av) is not installed.", exception=exc)
        ) from exc


def host_only_configuration() -> Any:
    """RTCConfiguration with no STUN/TURN — host candidates only."""
    require_aiortc()
    from aiortc import RTCConfiguration

    return RTCConfiguration(iceServers=[])


def create_peer_connection() -> Any:
    """Create an RTCPeerConnection configured for LAN host ICE only."""
    require_aiortc()
    from aiortc import RTCPeerConnection

    return RTCPeerConnection(configuration=host_only_configuration())


def list_video_codecs() -> list[AvailableCodec]:
    """Return available video codecs from aiortc sender capabilities."""
    require_aiortc()
    from aiortc import RTCRtpSender

    caps = RTCRtpSender.getCapabilities("video")
    codecs: list[AvailableCodec] = []
    for codec in caps.codecs:
        codecs.append(
            AvailableCodec(
                mime_type=str(getattr(codec, "mimeType", "")),
                clock_rate=getattr(codec, "clockRate", None),
                channels=getattr(codec, "channels", None),
                sdp_fmtp_line=getattr(codec, "sdpFmtpLine", None),
            )
        )
    return codecs


def _mime_is(codec: Any, name: str) -> bool:
    mime = str(getattr(codec, "mimeType", "") or "").lower()
    return mime == name.lower()


def assert_preferred_video_codec_available(
    *,
    prefer: str = "video/VP8",
    allow_h264_fallback: bool = False,
) -> str:
    """Validate preferred codec availability without mutating a peer connection."""
    require_aiortc()
    from aiortc import RTCRtpSender

    caps = RTCRtpSender.getCapabilities("video")
    all_codecs = list(caps.codecs)
    available = [str(getattr(c, "mimeType", "")) for c in all_codecs]
    preferred = [c for c in all_codecs if _mime_is(c, prefer)]
    h264 = [c for c in all_codecs if _mime_is(c, "video/H264")]
    if prefer.upper().endswith("VP8") and not preferred:
        if allow_h264_fallback and h264:
            return "H264"
        raise WebRTCError(
            failure_for(
                "VP8_UNAVAILABLE",
                "VP8 codec is not available.",
                likely_cause=(
                    "aiortc/PyAV did not advertise video/VP8. "
                    f"Available: {', '.join(available) or '(none)'}"
                ),
            )
        )
    if not preferred:
        raise WebRTCError(
            failure_for(
                "VP8_UNAVAILABLE",
                f"Preferred codec {prefer} is not available.",
                likely_cause=f"Available: {', '.join(available) or '(none)'}",
            )
        )
    return prefer.split("/")[-1].upper()


def prefer_video_codec(
    pc: Any,
    *,
    prefer: str = "video/VP8",
    allow_h264_fallback: bool = False,
) -> str:
    """Prefer *prefer* on all video transceivers.

    Returns the selected codec mime family name (e.g. ``VP8``).
    Raises :class:`WebRTCError` with ``VP8_UNAVAILABLE`` when VP8 is missing and
    fallback is not allowed.
    """
    require_aiortc()
    from aiortc import RTCRtpSender

    selected = assert_preferred_video_codec_available(
        prefer=prefer,
        allow_h264_fallback=allow_h264_fallback,
    )
    caps = RTCRtpSender.getCapabilities("video")
    all_codecs = list(caps.codecs)
    if selected == "H264":
        preferred = [c for c in all_codecs if _mime_is(c, "video/H264")]
    else:
        preferred = [c for c in all_codecs if _mime_is(c, prefer)]

    # Put preferred codecs first; keep others after for negotiation safety.
    ordered = preferred + [c for c in all_codecs if c not in preferred]
    for transceiver in pc.getTransceivers():
        if getattr(transceiver, "kind", None) == "video":
            try:
                transceiver.setCodecPreferences(ordered)
            except Exception as exc:
                raise WebRTCError(
                    failure_for(
                        "UNEXPECTED_WEBRTC_ERROR",
                        "Failed to set video codec preferences.",
                        exception=exc,
                    )
                ) from exc
    return selected


async def wait_ice_gathering_complete(pc: Any, *, timeout_s: float) -> None:
    """Wait until ICE gathering is complete or raise ICE_GATHERING_TIMEOUT."""
    import asyncio

    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    def _on_gather() -> None:
        if pc.iceGatheringState == "complete":
            done.set()

    pc.on("icegatheringstatechange")(_on_gather)

    if pc.iceGatheringState == "complete":
        done.set()
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout_s)
    except TimeoutError as exc:
        raise WebRTCError(
            failure_for(
                "ICE_GATHERING_TIMEOUT",
                f"ICE gathering did not complete within {timeout_s:.1f}s.",
                ice_state=str(getattr(pc, "iceConnectionState", None)),
                peer_state=str(getattr(pc, "connectionState", None)),
                signaling_state=str(getattr(pc, "signalingState", None)),
                exception=exc,
            )
        ) from exc


async def wait_ice_connected(pc: Any, *, timeout_s: float) -> None:
    """Wait until ICE connection state is connected/completed."""
    import asyncio

    success = {"connected", "completed"}
    failed = {"failed", "closed", "disconnected"}
    if pc.iceConnectionState in success:
        return
    done = asyncio.Event()
    error_state: list[str] = []

    def _on_ice() -> None:
        state = pc.iceConnectionState
        if state in success:
            done.set()
        elif state in failed:
            error_state.append(state)
            done.set()

    pc.on("iceconnectionstatechange")(_on_ice)

    if pc.iceConnectionState in success:
        done.set()
    elif pc.iceConnectionState in failed:
        error_state.append(pc.iceConnectionState)
        done.set()

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout_s)
    except TimeoutError as exc:
        raise WebRTCError(
            failure_for(
                "ICE_CONNECTION_FAILED",
                f"ICE connection did not succeed within {timeout_s:.1f}s "
                f"(state={pc.iceConnectionState}).",
                ice_state=str(pc.iceConnectionState),
                peer_state=str(getattr(pc, "connectionState", None)),
                signaling_state=str(getattr(pc, "signalingState", None)),
                exception=exc,
            )
        ) from exc

    if error_state or pc.iceConnectionState in failed:
        raise WebRTCError(
            failure_for(
                "ICE_CONNECTION_FAILED",
                f"ICE connection failed (state={pc.iceConnectionState}).",
                ice_state=str(pc.iceConnectionState),
                peer_state=str(getattr(pc, "connectionState", None)),
                signaling_state=str(getattr(pc, "signalingState", None)),
            )
        )


def collect_local_candidate_strings(pc: Any) -> list[str]:
    """Extract candidate lines from the local SDP (non-trickle snapshot)."""
    desc = getattr(pc, "localDescription", None)
    if desc is None or not getattr(desc, "sdp", None):
        return []
    lines: list[str] = []
    for line in str(desc.sdp).splitlines():
        stripped = line.strip()
        if stripped.startswith("a=candidate:") or stripped.startswith("candidate:"):
            lines.append(stripped)
    return lines


def sdp_type_ok(sdp_type: str, expected: Sequence[str]) -> bool:
    return sdp_type.lower() in {e.lower() for e in expected}
