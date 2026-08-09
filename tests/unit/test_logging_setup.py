"""Unit tests for secret redaction logging filter."""

from __future__ import annotations

import logging
from pathlib import Path

from snowlink.logging_setup import SecretRedactionFilter, read_recent_log_lines


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


def test_read_recent_log_lines_tail(tmp_path: Path) -> None:
    log_file = tmp_path / "snowlink.log"
    log_file.write_text("\n".join(f"line-{i}" for i in range(20)) + "\n", encoding="utf-8")
    lines = read_recent_log_lines(5, log_dir=tmp_path)
    assert lines == [f"line-{i}" for i in range(15, 20)]


def test_read_recent_log_lines_missing(tmp_path: Path) -> None:
    assert read_recent_log_lines(10, log_dir=tmp_path) == []
