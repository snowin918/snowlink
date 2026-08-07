"""High-entropy identifiers and session secrets (in-memory only)."""

from __future__ import annotations

import secrets
import uuid


def generate_session_id() -> str:
    """Return a stable per-share-session identifier."""
    return str(uuid.uuid4())


def generate_msg_id() -> str:
    """Return a unique signaling message id."""
    return str(uuid.uuid4())


def generate_session_secret() -> str:
    """Return a high-entropy per-session secret (not the 6-digit pairing code)."""
    return secrets.token_urlsafe(32)
