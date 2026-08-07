"""Unit tests for secret redaction logging filter."""

from __future__ import annotations

import logging

from snowlink.logging_setup import SecretRedactionFilter


def test_redacts_pairing_code_in_pairing_context() -> None:
    filt = SecretRedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="pairing code 483920 accepted",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert "483920" not in record.getMessage()
    assert "******" in record.getMessage()


def test_redacts_session_secret_key() -> None:
    filt = SecretRedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="session_secret=abc123XYZ",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert "abc123XYZ" not in record.getMessage()
