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
    """Return a known media-engine name; unknown values fall back to legacy."""
    if name is None:
        return MEDIA_ENGINE_LEGACY_PYTHON
    normalized = str(name).strip().lower()
    if normalized in KNOWN_MEDIA_ENGINES:
        return normalized  # type: ignore[return-value]
    return MEDIA_ENGINE_LEGACY_PYTHON


def resolve_effective_media_engine(
    requested: str | None,
    *,
    native_available: bool,
) -> MediaEngineName:
    """Choose the engine that will actually run sessions today.

    ``native_cpp`` is selectable for lifecycle probing, but production share/view
    still uses ``legacy_python`` until capture/encode/transport are migrated.
    """
    wanted = normalize_media_engine(requested)
    if wanted == MEDIA_ENGINE_NATIVE_CPP and not native_available:
        return MEDIA_ENGINE_LEGACY_PYTHON
    # Streaming path is not wired for native yet — keep sessions on legacy.
    if wanted == MEDIA_ENGINE_NATIVE_CPP:
        return MEDIA_ENGINE_LEGACY_PYTHON
    return wanted
