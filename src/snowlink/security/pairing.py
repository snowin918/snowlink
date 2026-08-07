"""6-digit pairing codes, TTL, rate limits, and approval gating."""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from snowlink.constants import (
    PAIRING_CODE_DIGITS,
    PAIRING_RATE_LIMIT_FAILURES,
    PAIRING_RATE_LIMIT_WINDOW_S,
    PAIRING_TTL_S,
)


class PairingResultStatus(StrEnum):
    OK = "ok"
    DENIED = "denied"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class PairingRequestInfo:
    """Viewer pairing attempt presented to the sharer for approval."""

    remote_addr: str
    code_matched: bool
    session_id: str


@dataclass
class RateLimiter:
    """Sliding-window failure counter keyed by source IP."""

    max_failures: int = PAIRING_RATE_LIMIT_FAILURES
    window_s: float = PAIRING_RATE_LIMIT_WINDOW_S
    _failures: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def is_limited(self, key: str, *, now: float | None = None) -> bool:
        self._prune(key, now=now)
        return len(self._failures[key]) >= self.max_failures

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        ts = time.monotonic() if now is None else now
        self._failures[key].append(ts)
        self._prune(key, now=ts)

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)

    def _prune(self, key: str, *, now: float | None = None) -> None:
        ts = time.monotonic() if now is None else now
        bucket = self._failures[key]
        cutoff = ts - self.window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()


def generate_pairing_code(*, digits: int = PAIRING_CODE_DIGITS) -> str:
    """Return a cryptographically random numeric pairing code."""
    if digits < 4 or digits > 10:
        raise ValueError("pairing code digits must be in 4..10")
    upper = 10**digits
    return f"{secrets.randbelow(upper):0{digits}d}"


def codes_equal(a: str, b: str) -> bool:
    """Constant-time compare for pairing codes (same length required)."""
    left = a.strip().encode("utf-8")
    right = b.strip().encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


@dataclass
class PairingAuthority:
    """Owns the share-session pairing code, nonce, TTL, and rate limits."""

    session_id: str
    code: str = field(default_factory=generate_pairing_code)
    ttl_s: float = PAIRING_TTL_S
    created_at: float = field(default_factory=time.monotonic)
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    _nonce: str | None = field(default=None, init=False, repr=False)
    _consumed: bool = field(default=False, init=False)

    def remaining_ttl_s(self, *, now: float | None = None) -> float:
        ts = time.monotonic() if now is None else now
        return max(0.0, self.ttl_s - (ts - self.created_at))

    def is_expired(self, *, now: float | None = None) -> bool:
        return self.remaining_ttl_s(now=now) <= 0.0

    def issue_challenge(self, *, now: float | None = None) -> tuple[str, float]:
        """Return (nonce, expiry_unix_ms) for pairing_challenge."""
        if self.is_expired(now=now):
            raise TimeoutError("pairing code expired")
        self._nonce = secrets.token_urlsafe(16)
        expiry_ms = int((time.time() + self.remaining_ttl_s(now=now)) * 1000)
        return self._nonce, float(expiry_ms)

    def validate_response(
        self,
        *,
        code: str,
        nonce: str,
        remote_addr: str,
        now: float | None = None,
    ) -> Literal[
        PairingResultStatus.OK,
        PairingResultStatus.EXPIRED,
        PairingResultStatus.RATE_LIMITED,
        PairingResultStatus.INVALID,
    ]:
        """Validate pairing_response before the human approval step."""
        if self._consumed:
            return PairingResultStatus.INVALID
        if self.rate_limiter.is_limited(remote_addr, now=now):
            return PairingResultStatus.RATE_LIMITED
        if self.is_expired(now=now):
            return PairingResultStatus.EXPIRED
        if self._nonce is None or not hmac.compare_digest(self._nonce, nonce):
            self.rate_limiter.record_failure(remote_addr, now=now)
            return PairingResultStatus.INVALID
        if not codes_equal(code, self.code):
            self.rate_limiter.record_failure(remote_addr, now=now)
            return PairingResultStatus.INVALID
        return PairingResultStatus.OK

    def mark_consumed(self) -> None:
        self._consumed = True
        self._nonce = None
