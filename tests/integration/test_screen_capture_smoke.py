"""Integration smoke tests for Experiment C (no real DXcam required by default)."""

from __future__ import annotations

import sys
import time
from typing import Any

import pytest

from snowlink.media.capture_models import CaptureConfiguration
from snowlink.media.screen_capture import ScreenCaptureSession


class _FakeFrame:
    def __init__(self, value: int) -> None:
        self.value = value
        self.shape = (48, 64, 3)

    def copy(self) -> _FakeFrame:
        return _FakeFrame(self.value)


def test_synthetic_capture_pipeline_runs_and_shuts_down() -> None:
    counter = {"n": 0}

    def grab() -> Any:
        counter["n"] += 1
        if counter["n"] % 3 == 0:
            return None
        return _FakeFrame(counter["n"])

    config = CaptureConfiguration(
        monitor=0,
        backend="dxgi",
        requested_fps=60,
        requested_width=64,
        requested_height=48,
        duration_s=1,
        show_preview=False,
    )
    session = ScreenCaptureSession(config, grabber=grab)
    session.start()
    time.sleep(0.2)
    # Consume a few frames like the preview loop would.
    rendered = 0
    for _ in range(20):
        item = session.slot.take(clear=True)
        if item is not None:
            rendered += 1
            session.timings.add_frame_age_ns(
                time.perf_counter_ns() - item.captured_at_ns
            )
        time.sleep(0.005)
    session.shutdown(join_timeout_s=2.0)
    assert session._worker_stats.frames_captured > 0
    assert session._worker_stats.null_frames >= 0
    assert session.slot.closed
    result = session.build_partial_result(
        frames_rendered=rendered,
        success=True,
        errors=[],
    )
    assert result.capture.frames_captured > 0
    assert result.configuration is not None


@pytest.mark.hardware
@pytest.mark.skipif(sys.platform != "win32", reason="DXcam is Windows-only")
def test_real_dxcam_grab_optional() -> None:
    """Optional live grab; run with: pytest -m hardware"""
    dxcam = pytest.importorskip("dxcam")
    camera = dxcam.create(output_color="BGR", max_buffer_len=2, backend="dxgi")
    try:
        frame = None
        for _ in range(30):
            frame = camera.grab()
            if frame is not None:
                break
            time.sleep(0.05)
        assert frame is not None
        assert frame.shape[0] > 0 and frame.shape[1] > 0
    finally:
        camera.release()
