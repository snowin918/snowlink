"""Media-engine backend selection (orthogonal to DXcam capture backend)."""

from __future__ import annotations

from typing import Literal

MediaEngineName = Literal["legacy_python", "native_cpp"]

MEDIA_ENGINE_LEGACY_PYTHON: MediaEngineName = "legacy_python"
MEDIA_ENGINE_NATIVE_CPP: MediaEngineName = "native_cpp"
KNOWN_MEDIA_ENGINES: tuple[MediaEngineName, ...] = (
    MEDIA_ENGINE_LEGACY_PYTHON,
    MEDIA_ENGINE_NATIVE_CPP,
)


def normalize_media_engine(name: str | None) -> MediaEngineName:
    """Return a known media-engine name; missing/unknown values use native."""
    if name is None:
        return MEDIA_ENGINE_NATIVE_CPP
    normalized = str(name).strip().lower()
    if normalized in KNOWN_MEDIA_ENGINES:
        return normalized  # type: ignore[return-value]
    return MEDIA_ENGINE_NATIVE_CPP


def resolve_effective_media_engine(
    requested: str | None,
    *,
    native_available: bool,
) -> MediaEngineName:
    """Choose the requested engine, falling back if the native DLL is absent."""
    wanted = normalize_media_engine(requested)
    if wanted == MEDIA_ENGINE_NATIVE_CPP and not native_available:
        return MEDIA_ENGINE_LEGACY_PYTHON
    return wanted
