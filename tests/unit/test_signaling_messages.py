"""Unit tests for WebSocket signaling message schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from snowlink.constants import PROTOCOL_VERSION
from snowlink.net.messages import (
    HelloPayload,
    PairingResponsePayload,
    SdpPayload,
    make_envelope,
    parse_envelope,
)


def test_make_and_parse_hello_roundtrip() -> None:
    env = make_envelope(
        session_id="sess-1",
        msg_type="hello",
        payload=HelloPayload(),
    )
    raw = env.model_dump_json()
    parsed = parse_envelope(raw)
    assert parsed.type == "hello"
    assert parsed.v == PROTOCOL_VERSION
    assert parsed.session_id == "sess-1"


def test_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        parse_envelope(
            {
                "v": PROTOCOL_VERSION,
                "session_id": "s",
                "msg_id": "m",
                "ts": 1,
                "type": "hello",
                "payload": {"role": "viewer", "extra": True},
            }
        )


def test_reject_bad_pairing_code() -> None:
    with pytest.raises(ValidationError):
        PairingResponsePayload(code="12ab", nonce="n")


def test_sdp_payload_requires_nonempty() -> None:
    with pytest.raises(ValidationError):
        SdpPayload(sdp="   ", sdp_type="offer")
    ok = SdpPayload(sdp="v=0", sdp_type="answer")
    assert ok.sdp_type == "answer"


def test_protocol_version_mismatch() -> None:
    with pytest.raises(ValidationError):
        parse_envelope(
            {
                "v": 99,
                "session_id": "s",
                "msg_id": "m",
                "ts": 1,
                "type": "ping",
                "payload": {"t0": 1.0},
            }
        )
