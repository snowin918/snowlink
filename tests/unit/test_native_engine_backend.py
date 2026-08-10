"""Unit tests for media-engine selection helpers (no DLL required)."""

from __future__ import annotations

from snowlink.native_engine.backend import (
    MEDIA_ENGINE_LEGACY_PYTHON,
    MEDIA_ENGINE_NATIVE_CPP,
    normalize_media_engine,
    resolve_effective_media_engine,
)


def test_normalize_media_engine_defaults() -> None:
    assert normalize_media_engine(None) == MEDIA_ENGINE_NATIVE_CPP
    assert normalize_media_engine("legacy_python") == MEDIA_ENGINE_LEGACY_PYTHON
    assert normalize_media_engine("NATIVE_CPP") == MEDIA_ENGINE_NATIVE_CPP
    assert normalize_media_engine("unknown") == MEDIA_ENGINE_NATIVE_CPP


def test_resolve_effective_prefers_available_native() -> None:
    assert (
        resolve_effective_media_engine(MEDIA_ENGINE_NATIVE_CPP, native_available=True)
        == MEDIA_ENGINE_NATIVE_CPP
    )
    assert (
        resolve_effective_media_engine(MEDIA_ENGINE_NATIVE_CPP, native_available=False)
        == MEDIA_ENGINE_LEGACY_PYTHON
    )
    assert (
        resolve_effective_media_engine(MEDIA_ENGINE_LEGACY_PYTHON, native_available=True)
        == MEDIA_ENGINE_LEGACY_PYTHON
    )
