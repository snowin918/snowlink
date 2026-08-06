"""Unit tests for capture configuration validation and presets."""

from __future__ import annotations

import pytest

from snowlink.media.capture_errors import CaptureError
from snowlink.media.capture_models import (
    DEFAULT_PRESET,
    MAX_DIMENSION,
    MAX_DURATION_S,
    MAX_FPS,
    PRESETS,
    resolve_preset,
    validate_backend,
    validate_capture_configuration,
)
from snowlink.media.scaling import compute_letterbox_geometry


def test_default_balanced_preset() -> None:
    assert DEFAULT_PRESET.width == 1280
    assert DEFAULT_PRESET.height == 720
    assert DEFAULT_PRESET.fps == 30
    assert PRESETS["balanced"] == DEFAULT_PRESET


def test_preset_resolution() -> None:
    low = resolve_preset("Low")
    assert (low.width, low.height, low.fps) == (854, 480, 15)
    high = resolve_preset("high")
    assert (high.width, high.height, high.fps) == (1920, 1080, 30)


def test_unknown_preset_raises() -> None:
    with pytest.raises(CaptureError) as exc:
        resolve_preset("ultra")
    assert exc.value.failure.code == "INVALID_CONFIGURATION"


def test_validate_backend() -> None:
    assert validate_backend("DXGI") == "dxgi"
    assert validate_backend("winrt") == "winrt"
    with pytest.raises(CaptureError) as exc:
        validate_backend("opengl")
    assert exc.value.failure.code == "BACKEND_UNAVAILABLE"


def test_fps_and_dimension_validation() -> None:
    cfg = validate_capture_configuration(
        monitor=0,
        backend="dxgi",
        fps=30,
        width=1280,
        height=720,
        duration=60,
    )
    assert cfg.requested_fps == 30

    with pytest.raises(CaptureError) as exc:
        validate_capture_configuration(
            monitor=0,
            backend="dxgi",
            fps=0,
            width=1280,
            height=720,
            duration=60,
        )
    assert exc.value.failure.code == "INVALID_CONFIGURATION"

    with pytest.raises(CaptureError):
        validate_capture_configuration(
            monitor=0,
            backend="dxgi",
            fps=MAX_FPS + 1,
            width=1280,
            height=720,
            duration=60,
        )

    with pytest.raises(CaptureError):
        validate_capture_configuration(
            monitor=0,
            backend="dxgi",
            fps=30,
            width=0,
            height=720,
            duration=60,
        )

    with pytest.raises(CaptureError):
        validate_capture_configuration(
            monitor=0,
            backend="dxgi",
            fps=30,
            width=MAX_DIMENSION + 1,
            height=720,
            duration=60,
        )

    with pytest.raises(CaptureError):
        validate_capture_configuration(
            monitor=0,
            backend="dxgi",
            fps=30,
            width=1280,
            height=720,
            duration=MAX_DURATION_S + 1,
        )

    with pytest.raises(CaptureError) as mon_exc:
        validate_capture_configuration(
            monitor=-1,
            backend="dxgi",
            fps=30,
            width=1280,
            height=720,
            duration=60,
        )
    assert mon_exc.value.failure.code == "INVALID_MONITOR"


def test_aspect_ratio_scaling_calculations() -> None:
    # 1920x1080 into 1280x720 — exact fit, no padding.
    g = compute_letterbox_geometry(1920, 1080, 1280, 720)
    assert g.content_width == 1280
    assert g.content_height == 720
    assert g.pad_left == 0 and g.pad_right == 0
    assert g.pad_top == 0 and g.pad_bottom == 0

    # Wider source into square-ish box → pillarbox.
    g2 = compute_letterbox_geometry(1920, 1080, 800, 800)
    assert g2.content_width == 800
    assert g2.content_height == 450
    assert g2.pad_top + g2.pad_bottom == 350
    assert g2.pad_left == 0 and g2.pad_right == 0

    # Taller source → letterbox.
    g3 = compute_letterbox_geometry(1080, 1920, 1280, 720)
    assert g3.content_height == 720
    assert g3.pad_left + g3.pad_right > 0
