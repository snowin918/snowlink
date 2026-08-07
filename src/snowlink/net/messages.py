"""Versioned WebSocket signaling message schemas (pydantic v2)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from snowlink.constants import PROTOCOL_VERSION
from snowlink.security.secrets import generate_msg_id

MessageType = Literal[
    "hello",
    "hello_ack",
    "pairing_challenge",
    "pairing_response",
    "pairing_result",
    "offer",
    "answer",
    "ice_candidate",
    "state",
    "error",
    "disconnect",
    "ping",
    "pong",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelloPayload(_StrictModel):
    role: Literal["viewer"] = "viewer"
    client_name: str = "snowlink"
    capabilities: list[str] = Field(default_factory=lambda: ["vp8", "opus"])


class HelloAckPayload(_StrictModel):
    server_version: int = PROTOCOL_VERSION
    requires_pairing: bool = True
    role: Literal["sharer"] = "sharer"


class PairingChallengePayload(_StrictModel):
    nonce: str
    expiry_ms: float


class PairingResponsePayload(_StrictModel):
    code: str
    nonce: str
    client_proof: str = ""

    @field_validator("code")
    @classmethod
    def _digits(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.isdigit() or len(cleaned) < 4 or len(cleaned) > 10:
            raise ValueError("pairing code must be 4–10 digits")
        return cleaned


class PairingResultPayload(_StrictModel):
    status: Literal["ok", "denied", "expired", "rate_limited", "invalid"]
    session_secret: str | None = None
    message: str = ""


class SdpPayload(_StrictModel):
    sdp: str
    sdp_type: Literal["offer", "answer"]

    @field_validator("sdp")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sdp must be non-empty")
        return value


class IceCandidatePayload(_StrictModel):
    candidate: str | None = None
    sdpMid: str | None = None
    sdpMLineIndex: int | None = None
    completed: bool = False


class StatePayload(_StrictModel):
    phase: str
    detail: str = ""


class ErrorPayload(_StrictModel):
    code: str
    message: str


class DisconnectPayload(_StrictModel):
    reason: str = "bye"


class PingPayload(_StrictModel):
    t0: float


class PongPayload(_StrictModel):
    t0: float
    t1: float


class Envelope(_StrictModel):
    """Common envelope for all signaling messages."""

    v: int = PROTOCOL_VERSION
    session_id: str
    msg_id: str = Field(default_factory=generate_msg_id)
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("v")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version {value}")
        return value


_PAYLOAD_BY_TYPE: dict[str, type[BaseModel]] = {
    "hello": HelloPayload,
    "hello_ack": HelloAckPayload,
    "pairing_challenge": PairingChallengePayload,
    "pairing_response": PairingResponsePayload,
    "pairing_result": PairingResultPayload,
    "offer": SdpPayload,
    "answer": SdpPayload,
    "ice_candidate": IceCandidatePayload,
    "state": StatePayload,
    "error": ErrorPayload,
    "disconnect": DisconnectPayload,
    "ping": PingPayload,
    "pong": PongPayload,
}

_ENVELOPE_ADAPTER: TypeAdapter[Envelope] = TypeAdapter(Envelope)


def make_envelope(
    *,
    session_id: str,
    msg_type: MessageType,
    payload: BaseModel | dict[str, Any],
    msg_id: str | None = None,
) -> Envelope:
    raw = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
    return Envelope(
        session_id=session_id,
        msg_id=msg_id or generate_msg_id(),
        type=msg_type,
        payload=raw,
    )


def parse_envelope(data: dict[str, Any] | str | bytes) -> Envelope:
    """Parse and validate an envelope; also validates the typed payload."""
    if isinstance(data, (bytes, bytearray)):
        envelope = _ENVELOPE_ADAPTER.validate_json(data)
    elif isinstance(data, str):
        envelope = _ENVELOPE_ADAPTER.validate_json(data)
    else:
        envelope = _ENVELOPE_ADAPTER.validate_python(data)
    model = _PAYLOAD_BY_TYPE.get(envelope.type)
    if model is None:
        raise ValueError(f"unknown message type: {envelope.type}")
    # Re-validate payload with the concrete model (extra=forbid).
    model.model_validate(envelope.payload)
    return envelope


def typed_payload(envelope: Envelope) -> BaseModel:
    model = _PAYLOAD_BY_TYPE[envelope.type]
    return model.model_validate(envelope.payload)


# Convenience: payload model map is private; use typed_payload() / parse_envelope().

