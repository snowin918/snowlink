"""Signaling connection state labels (share / view / WS)."""

from __future__ import annotations

from enum import StrEnum


class SignalingState(StrEnum):
    CLOSED = "closed"
    LISTENING = "listening"
    DIALING = "dialing"
    HANDSHAKE = "handshake"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    MEDIA_SIGNALING = "media_signaling"
    CLOSING = "closing"


# States that may accept offer / answer / ice_candidate.
MEDIA_READY_STATES = frozenset(
    {
        SignalingState.AUTHENTICATED,
        SignalingState.MEDIA_SIGNALING,
    }
)
