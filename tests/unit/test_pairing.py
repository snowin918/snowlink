"""Unit tests for pairing codes, TTL, and rate limits."""

from __future__ import annotations

import time

from snowlink.security.pairing import (
    PairingAuthority,
    PairingResultStatus,
    RateLimiter,
    codes_equal,
    generate_pairing_code,
)
from snowlink.security.secrets import generate_session_id, generate_session_secret


def test_generate_pairing_code_is_six_digits() -> None:
    code = generate_pairing_code()
    assert len(code) == 6
    assert code.isdigit()


def test_codes_equal_constant_time() -> None:
    assert codes_equal("123456", "123456")
    assert not codes_equal("123456", "123457")
    assert not codes_equal("12345", "123456")


def test_pairing_authority_happy_path() -> None:
    auth = PairingAuthority(session_id=generate_session_id(), code="424242")
    nonce, expiry = auth.issue_challenge()
    assert nonce
    assert expiry > 0
    status = auth.validate_response(
        code="424242",
        nonce=nonce,
        remote_addr="192.168.1.10",
    )
    assert status == PairingResultStatus.OK


def test_pairing_authority_wrong_code_rate_limits() -> None:
    auth = PairingAuthority(
        session_id=generate_session_id(),
        code="111111",
        rate_limiter=RateLimiter(max_failures=3, window_s=60.0),
    )
    for _ in range(3):
        nonce, _ = auth.issue_challenge()
        status = auth.validate_response(
            code="000000",
            nonce=nonce,
            remote_addr="10.0.0.2",
        )
        assert status == PairingResultStatus.INVALID
    nonce, _ = auth.issue_challenge()
    status = auth.validate_response(
        code="111111",
        nonce=nonce,
        remote_addr="10.0.0.2",
    )
    assert status == PairingResultStatus.RATE_LIMITED


def test_pairing_authority_expired() -> None:
    auth = PairingAuthority(
        session_id=generate_session_id(),
        code="222222",
        ttl_s=0.01,
        created_at=time.monotonic() - 1.0,
    )
    try:
        auth.issue_challenge()
        raised = False
    except TimeoutError:
        raised = True
    assert raised


def test_session_secret_entropy() -> None:
    a = generate_session_secret()
    b = generate_session_secret()
    assert a != b
    assert len(a) >= 32
