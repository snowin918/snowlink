"""Python control surface for the native C++ Snowlink media engine.

Frames never cross this boundary — only commands, status, and statistics.
"""

from __future__ import annotations

from snowlink.native_engine.backend import (
    MEDIA_ENGINE_LEGACY_PYTHON,
    MEDIA_ENGINE_NATIVE_CPP,
    KNOWN_MEDIA_ENGINES,
    normalize_media_engine,
    resolve_effective_media_engine,
)
from snowlink.native_engine.engine import (
    NativeEngine,
    NativeEngineError,
    NativeEngineStats,
    NativeEngineUnavailable,
    is_native_engine_available,
    probe_native_engine,
)

__all__ = [
    "MEDIA_ENGINE_LEGACY_PYTHON",
    "MEDIA_ENGINE_NATIVE_CPP",
    "KNOWN_MEDIA_ENGINES",
    "NativeEngine",
    "NativeEngineError",
    "NativeEngineStats",
    "NativeEngineUnavailable",
    "is_native_engine_available",
    "normalize_media_engine",
    "probe_native_engine",
    "resolve_effective_media_engine",
]
