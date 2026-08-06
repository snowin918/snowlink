"""Structured WebRTC errors for Experiments E/F (synthetic video/audio)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WebRTCFailure:
    """Machine-readable WebRTC failure with safe operator guidance."""

    code: str
    message: str
    likely_cause: str = ""
    suggested_next_step: str = ""
    exception_type: str | None = None
    signaling_state: str | None = None
    ice_state: str | None = None
    peer_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAUSES: dict[str, str] = {
    "AIORTC_NOT_INSTALLED": (
        "The aiortc package is not installed in the active Python environment."
    ),
    "PYAV_NOT_INSTALLED": (
        "The PyAV (av) package is not installed in the active Python environment."
    ),
    "VP8_UNAVAILABLE": (
        "VP8 is not available in the local aiortc / PyAV codec list."
    ),
    "OPUS_UNAVAILABLE": (
        "Opus is not available in the local aiortc / PyAV codec list."
    ),
    "INVALID_BIND_IP": (
        "The requested bind or source IPv4 address is not a valid dotted IPv4."
    ),
    "IP_NOT_ASSIGNED": (
        "The requested IPv4 address is not assigned to any local network adapter."
    ),
    "SIGNALING_BIND_FAILED": (
        "The experiment signaling HTTP server could not bind to the requested address."
    ),
    "SIGNALING_CONNECTION_FAILED": (
        "The receiver could not open a TCP connection to the sender signaling endpoint."
    ),
    "SIGNALING_TIMEOUT": (
        "A signaling request timed out before offer/answer completed."
    ),
    "MALFORMED_SDP": (
        "The signaling payload was missing required fields or used an unexpected SDP type."
    ),
    "OFFER_REJECTED": (
        "The sender rejected the WebRTC offer (busy, invalid, or negotiation failure)."
    ),
    "ANSWER_REJECTED": (
        "The receiver rejected the WebRTC answer from the sender."
    ),
    "ICE_GATHERING_TIMEOUT": (
        "ICE host-candidate gathering did not complete within the configured timeout."
    ),
    "ICE_CONNECTION_FAILED": (
        "ICE could not establish a host-candidate UDP path between the peers."
    ),
    "ICE_SELECTED_WRONG_INTERFACE": (
        "ICE connected, but the selected local candidate is not the requested physical LAN IP."
    ),
    "DTLS_CONNECTION_FAILED": (
        "DTLS negotiation failed after ICE connectivity checks."
    ),
    "VIDEO_TRACK_NOT_RECEIVED": (
        "The receiver did not receive a remote video track after the peer connected."
    ),
    "VIDEO_FRAME_TIMEOUT": (
        "No remote video frames arrived within the first-frame timeout."
    ),
    "VIDEO_DECODE_FAILED": (
        "A remote video frame could not be decoded into a usable bitmap."
    ),
    "PREVIEW_FAILED": (
        "The experimental OpenCV preview window could not be created or updated."
    ),
    "AUDIO_TRACK_NOT_RECEIVED": (
        "The receiver did not receive a remote audio track after the peer connected."
    ),
    "FIRST_AUDIO_FRAME_TIMEOUT": (
        "No remote audio frames arrived within the first-frame timeout."
    ),
    "INVALID_AUDIO_FRAME": (
        "A remote audio frame had an unexpected format, layout, or sample count."
    ),
    "AUDIO_PTS_ERROR": (
        "Received audio PTS values were missing, duplicate, or decreasing."
    ),
    "PLAYBACK_DEVICE_NOT_FOUND": (
        "The requested WASAPI playback endpoint could not be resolved."
    ),
    "PLAYBACK_OPEN_FAILED": (
        "The WASAPI playback stream could not be opened."
    ),
    "PLAYBACK_WRITE_FAILED": (
        "Writing PCM to the playback stream failed."
    ),
    "AUDIO_BUFFER_UNDERRUN": (
        "The receiver audio ring buffer underran (missing data; silence inserted)."
    ),
    "AUDIO_BUFFER_OVERRUN": (
        "The receiver audio ring buffer overran (oldest samples dropped)."
    ),
    "PEER_DISCONNECTED": (
        "The remote peer disconnected before the experiment duration completed."
    ),
    "UNEXPECTED_WEBRTC_ERROR": (
        "An unexpected exception occurred in the WebRTC experiment pipeline."
    ),
    "UNEXPECTED_WEBRTC_AUDIO_ERROR": (
        "An unexpected exception occurred in the WebRTC audio experiment pipeline."
    ),
    "INVALID_CONFIGURATION": (
        "One or more experiment configuration values are outside the allowed ranges."
    ),
}

_ACTIONS: dict[str, str] = {
    "AIORTC_NOT_INSTALLED": (
        'Install WebRTC dependencies with: pip install -e ".[webrtc]"'
    ),
    "PYAV_NOT_INSTALLED": (
        'Install WebRTC dependencies with: pip install -e ".[webrtc]"'
    ),
    "VP8_UNAVAILABLE": (
        "Confirm aiortc/PyAV install; re-run and inspect available codecs. "
        "Only use --allow-h264-fallback if you explicitly want H.264."
    ),
    "OPUS_UNAVAILABLE": (
        "Confirm aiortc/PyAV install advertises audio/opus. Do not fall back to PCMU/PCMA."
    ),
    "INVALID_BIND_IP": (
        "Pass a dotted IPv4 such as 192.168.1.25 for --bind-ip / --source-ip."
    ),
    "IP_NOT_ASSIGNED": (
        "Run `python experiments/experiment_a_adapter_bind.py list` and pick an "
        "assigned physical LAN IPv4."
    ),
    "SIGNALING_BIND_FAILED": (
        "Confirm the IP is local, the port is free, and Windows Firewall allows the listen."
    ),
    "SIGNALING_CONNECTION_FAILED": (
        "Confirm the sender is listening, the remote IP/port are correct, and LAN TCP "
        "is allowed while VPNs are enabled (see Experiment B / docs/vpn-lan-access.md)."
    ),
    "SIGNALING_TIMEOUT": (
        "Retry; if persistent, check VPN allow-LAN / firewall and increase --timeouts."
    ),
    "MALFORMED_SDP": (
        "Ensure both peers run the same experiment script version; do not hand-edit SDP."
    ),
    "OFFER_REJECTED": (
        "Ensure only one receiver connects; restart the sender if a previous session stuck."
    ),
    "ANSWER_REJECTED": (
        "Restart both peers; confirm Opus/VP8 availability and matching experiment versions."
    ),
    "ICE_GATHERING_TIMEOUT": (
        "Check local adapters and firewall; host-only ICE should gather quickly on LAN."
    ),
    "ICE_CONNECTION_FAILED": (
        "UDP between the physical LAN IPs is likely blocked. Check Windows Firewall and "
        "VPN kill-switch / allow-LAN settings. Do not disable VPN security."
    ),
    "ICE_SELECTED_WRONG_INTERFACE": (
        "Record the selected candidate pair. Prefer physical LAN IPs; VPN selection is a "
        "diagnostic result, not a silent success."
    ),
    "DTLS_CONNECTION_FAILED": (
        "Retry the session; if ICE succeeds but DTLS fails, capture peer states and retry."
    ),
    "VIDEO_TRACK_NOT_RECEIVED": (
        "Confirm the sender added the synthetic track and negotiation completed."
    ),
    "VIDEO_FRAME_TIMEOUT": (
        "Check ICE selected pair and packet-loss stats; verify UDP is not blocked."
    ),
    "VIDEO_DECODE_FAILED": (
        "Confirm codec (VP8) availability on both peers; inspect available codec lists."
    ),
    "PREVIEW_FAILED": (
        "Use --no-preview for headless metrics, or ensure a desktop session for OpenCV."
    ),
    "AUDIO_TRACK_NOT_RECEIVED": (
        "Confirm the sender added the synthetic audio track and negotiation completed."
    ),
    "FIRST_AUDIO_FRAME_TIMEOUT": (
        "Check ICE selected pair and packet-loss stats; verify UDP audio is not blocked."
    ),
    "INVALID_AUDIO_FRAME": (
        "Inspect received format/layout/sample-rate; Opus decode should yield 48 kHz PCM."
    ),
    "AUDIO_PTS_ERROR": (
        "Inspect PTS continuity in results; regenerate with the Experiment F synthetic track."
    ),
    "PLAYBACK_DEVICE_NOT_FOUND": (
        "Use --playback-device default or a valid WASAPI output index from Experiment D list."
    ),
    "PLAYBACK_OPEN_FAILED": (
        "Confirm speakers/headphones are available; retry with --no-playback for metrics."
    ),
    "PLAYBACK_WRITE_FAILED": (
        "Retry; if persistent, use --no-playback to isolate WebRTC receive from WASAPI."
    ),
    "AUDIO_BUFFER_UNDERRUN": (
        "Treat as a metric/warning unless continuous; check jitter and network loss."
    ),
    "AUDIO_BUFFER_OVERRUN": (
        "Treat as a metric/warning; oldest samples are dropped to bound latency."
    ),
    "PEER_DISCONNECTED": (
        "Restart both peers; confirm duration and network path remain stable."
    ),
    "UNEXPECTED_WEBRTC_ERROR": (
        "Re-run with --json, capture the error code/states, and retry after a clean exit."
    ),
    "UNEXPECTED_WEBRTC_AUDIO_ERROR": (
        "Re-run with --json, capture the error code/states, and retry after a clean exit."
    ),
    "INVALID_CONFIGURATION": (
        "Adjust duration, port, sample-rate, channels, frame-ms, gain, or timeout flags."
    ),
}


def failure_for(
    code: str,
    message: str,
    *,
    exception: BaseException | None = None,
    likely_cause: str | None = None,
    suggested_next_step: str | None = None,
    signaling_state: str | None = None,
    ice_state: str | None = None,
    peer_state: str | None = None,
) -> WebRTCFailure:
    """Build a :class:`WebRTCFailure` with standard cause/action text."""
    return WebRTCFailure(
        code=code,
        message=message,
        likely_cause=likely_cause if likely_cause is not None else _CAUSES.get(code, ""),
        suggested_next_step=(
            suggested_next_step
            if suggested_next_step is not None
            else _ACTIONS.get(code, _ACTIONS["UNEXPECTED_WEBRTC_ERROR"])
        ),
        exception_type=type(exception).__name__ if exception is not None else None,
        signaling_state=signaling_state,
        ice_state=ice_state,
        peer_state=peer_state,
    )


def map_exception(exc: BaseException) -> WebRTCFailure:
    """Map a generic exception onto a structured WebRTC failure."""
    if isinstance(exc, WebRTCError):
        return exc.failure
    name = type(exc).__name__
    text = str(exc).lower()
    if isinstance(exc, ModuleNotFoundError):
        mod = str(exc).lower()
        if "aiortc" in mod:
            return failure_for(
                "AIORTC_NOT_INSTALLED",
                "aiortc is not installed.",
                exception=exc,
            )
        if mod.endswith("'av'") or " no module named 'av'" in f" {mod}":
            return failure_for(
                "PYAV_NOT_INSTALLED",
                "PyAV (av) is not installed.",
                exception=exc,
            )
    if "timed out" in text or "timeout" in text:
        return failure_for(
            "SIGNALING_TIMEOUT",
            f"Operation timed out ({name}).",
            exception=exc,
        )
    return failure_for(
        "UNEXPECTED_WEBRTC_AUDIO_ERROR"
        if "audio" in text
        else "UNEXPECTED_WEBRTC_ERROR",
        f"Unexpected WebRTC error ({name}).",
        exception=exc,
    )


def format_failure_human(failure: WebRTCFailure) -> str:
    """Render a multi-line operator-facing explanation."""
    lines = [f"{failure.code}: {failure.message}"]
    if failure.likely_cause:
        lines.extend(["", f"Likely cause: {failure.likely_cause}"])
    if failure.suggested_next_step:
        lines.extend(["", f"Suggested next step: {failure.suggested_next_step}"])
    states = []
    if failure.signaling_state:
        states.append(f"signaling={failure.signaling_state}")
    if failure.ice_state:
        states.append(f"ice={failure.ice_state}")
    if failure.peer_state:
        states.append(f"peer={failure.peer_state}")
    if states:
        lines.append("States: " + ", ".join(states))
    if failure.exception_type:
        lines.append(f"Exception type: {failure.exception_type}")
    return "\n".join(lines)


class WebRTCError(Exception):
    """Exception carrying a structured :class:`WebRTCFailure`."""

    def __init__(self, failure: WebRTCFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
