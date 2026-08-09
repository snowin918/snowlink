"""WinRT → DXGI fallback and CaptureError → WebRTC mapping."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from snowlink.media.capture_errors import CaptureError, failure_for
from snowlink.media.capture_models import CaptureConfiguration
from snowlink.rtc.errors import map_exception


def test_map_exception_preserves_capture_error_details() -> None:
    nested = ModuleNotFoundError("No module named 'winrt.windows.graphics.capture'")
    exc = CaptureError(
        failure_for(
            "BACKEND_UNAVAILABLE",
            "WinRT capture dependencies are missing from this build.",
            exception=nested,
        )
    )
    exc.__cause__ = nested
    failure = map_exception(exc)
    assert failure.code == "CAPTURE_FAILED"
    assert "WinRT" in failure.message
    assert "ModuleNotFoundError" in failure.message


def test_create_camera_with_fallback_uses_dxgi_when_winrt_missing() -> None:
    from snowlink.media import screen_capture as sc

    monitor = object()
    cfg = CaptureConfiguration(monitor=0, backend="winrt")
    sentinel = object()

    def fake_create(mon: object, config: CaptureConfiguration, **_kwargs: object) -> object:
        if config.backend == "winrt":
            nested = ModuleNotFoundError("No module named 'winrt.windows.graphics.capture'")
            err = CaptureError(
                failure_for(
                    "BACKEND_UNAVAILABLE",
                    "WinRT capture dependencies are missing from this build.",
                    exception=nested,
                )
            )
            raise err from nested
        assert config.backend == "dxgi"
        return sentinel

    with patch.object(sc, "create_camera", side_effect=fake_create):
        camera, backend = sc.create_camera_with_fallback(monitor, cfg)  # type: ignore[arg-type]
    assert camera is sentinel
    assert backend == "dxgi"


def test_create_camera_with_fallback_does_not_mask_other_errors() -> None:
    from snowlink.media import screen_capture as sc

    cfg = CaptureConfiguration(monitor=0, backend="winrt")

    def fake_create(*_a: object, **_k: object) -> object:
        raise CaptureError(
            failure_for(
                "INVALID_MONITOR",
                "Monitor 9 has no mapped DXcam device/output index.",
            )
        )

    with patch.object(sc, "create_camera", side_effect=fake_create):
        with pytest.raises(CaptureError) as caught:
            sc.create_camera_with_fallback(object(), cfg)  # type: ignore[arg-type]
    assert caught.value.failure.code == "INVALID_MONITOR"
