"""Protocol / unauthorized signaling tests."""

from __future__ import annotations

import json

import pytest

from snowlink.constants import MAX_SIGNALING_MESSAGE_BYTES, PROTOCOL_VERSION
from snowlink.net.messages import HelloPayload, make_envelope, parse_envelope
from snowlink.security.pairing import PairingAuthority, PairingResultStatus
from snowlink.security.secrets import generate_session_id


def test_oversized_payload_exceeds_limit() -> None:
    huge = "x" * (MAX_SIGNALING_MESSAGE_BYTES + 100)
    raw = json.dumps(
        {
            "v": PROTOCOL_VERSION,
            "session_id": "s",
            "msg_id": "m",
            "ts": 1,
            "type": "error",
            "payload": {"code": "X", "message": huge},
        }
    )
    assert len(raw.encode("utf-8")) > MAX_SIGNALING_MESSAGE_BYTES


def test_malformed_json_raises() -> None:
    with pytest.raises(Exception):
        parse_envelope("{not-json")


def test_hello_round_trip() -> None:
    env = make_envelope(session_id="sess", msg_type="hello", payload=HelloPayload())
    parsed = parse_envelope(env.model_dump_json())
    assert parsed.type == "hello"
    assert parsed.v == PROTOCOL_VERSION


def test_wrong_pairing_code_invalid() -> None:
    auth = PairingAuthority(session_id=generate_session_id(), code="123456")
    nonce, _ = auth.issue_challenge()
    status = auth.validate_response(
        code="000000",
        nonce=nonce,
        remote_addr="127.0.0.1",
    )
    assert status == PairingResultStatus.INVALID


def test_unknown_nonce_invalid() -> None:
    auth = PairingAuthority(session_id=generate_session_id(), code="123456")
    auth.issue_challenge()
    status = auth.validate_response(
        code="123456",
        nonce="not-a-real-nonce",
        remote_addr="127.0.0.1",
    )
    assert status == PairingResultStatus.INVALID
