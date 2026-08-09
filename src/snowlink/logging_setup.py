"""Structured logging with secret redaction for Snowlink."""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from snowlink.platform_win.paths import ensure_app_dirs, logs_dir

_PAIRING_CODE_RE = re.compile(r"\b(\d{6})\b")
_SECRET_KEY_RE = re.compile(
    r"(?i)(pairing[_ ]?code|session[_ ]?secret|client[_ ]?proof|nonce)\s*[:=]\s*\S+"
)
_SDP_BLOCK_RE = re.compile(
    r"(?is)(v=0\r?\n.*?)(?=\n\n|\Z)|(\"sdp\"\s*:\s*\")(.*?)(\")"
)


class SecretRedactionFilter(logging.Filter):
    """Redact pairing codes, session secrets, and SDP bodies from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = _SECRET_KEY_RE.sub(r"\1=<redacted>", msg)
        redacted = _SDP_BLOCK_RE.sub("[sdp redacted]", redacted)
        # Avoid blanking every 6-digit number in non-secret context by only
        # redacting when the message mentions pairing/code/secret.
        if re.search(r"(?i)pairing|secret|code", redacted):
            redacted = _PAIRING_CODE_RE.sub("******", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(
    *,
    level: int = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
) -> Path:
    """Configure root logging with rotation under ``%LOCALAPPDATA%\\Snowlink\\logs``.

    Returns the log directory used.
    """
    ensure_app_dirs()
    directory = log_dir or logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "snowlink.log"

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers on repeated setup (tests / re-entry).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    redaction = SecretRedactionFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.addFilter(redaction)
        root.addHandler(stream)

    logging.getLogger(__name__).debug("Logging initialized at %s", log_file)
    return directory


def log_file_path(*, log_dir: Path | None = None) -> Path:
    """Return the primary rotating log file path."""
    directory = log_dir or logs_dir()
    return directory / "snowlink.log"


def read_recent_log_lines(
    max_lines: int = 80,
    *,
    log_dir: Path | None = None,
) -> list[str]:
    """Return the last *max_lines* from the sanitized application log.

    Lines are already redacted by :class:`SecretRedactionFilter` when written.
    Returns an empty list when the log file is missing or unreadable.
    """
    path = log_file_path(log_dir=log_dir)
    if not path.is_file():
        return []
    try:
        # Read a bounded tail without loading multi-MB logs into memory.
        max_bytes = max(16_384, max_lines * 512)
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), 0)
            raw = handle.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()
        if size > max_bytes and lines:
            # Drop the first partial line from a mid-file seek.
            lines = lines[1:]
        return lines[-max(1, max_lines) :]
    except Exception:
        logging.getLogger(__name__).debug("Failed to read log tail", exc_info=True)
        return []
