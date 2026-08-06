"""Integration: local loopback screen share with a fake grabber (no DXcam)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from snowlink.media.capture_models import CaptureConfiguration
from snowlink.media.screen_capture import ScreenCaptureSession
from snowlink.rtc.screen_session import (
    ScreenShareConfiguration,
    ScreenViewConfiguration,
    run_screen_share,
    run_screen_view,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_screen_share_view_local_loopback() -> None:
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    pytest.importorskip("aiohttp")

    frame_seq = {"n": 0}

    def grab() -> np.ndarray:
        frame_seq["n"] += 1
        img = np.zeros((180, 320, 3), dtype=np.uint8)
        img[:, :, 1] = (frame_seq["n"] * 7) % 255
        return img

    capture = ScreenCaptureSession(
        CaptureConfiguration(
            requested_fps=15,
            requested_width=320,
            requested_height=180,
            duration_s=30,
            show_preview=False,
            preset_name="low",
        ),
        grabber=grab,
    )
    capture.start()

    share_stop = asyncio.Event()
    view_stop = asyncio.Event()
    port = 19847

    share_config = ScreenShareConfiguration(
        bind_ip="127.0.0.1",
        signaling_port=port,
        width=320,
        height=180,
        fps=15,
        preset="low",
    )
    view_config = ScreenViewConfiguration(
        remote_ip="127.0.0.1",
        signaling_port=port,
        requested_source_ip="127.0.0.1",
        preview=False,
    )

    frames_seen = {"n": 0}

    def on_frame(bgr: np.ndarray) -> None:
        frames_seen["n"] += 1
        if frames_seen["n"] >= 5:
            view_stop.set()
            share_stop.set()

    async def share_task() -> None:
        await run_screen_share(
            share_config,
            stop_event=share_stop,
            capture_session=capture,
        )

    async def view_task() -> None:
        # Give the sharer a moment to bind.
        await asyncio.sleep(0.4)
        await run_screen_view(
            view_config,
            stop_event=view_stop,
            on_frame=on_frame,
        )

    try:
        results = await asyncio.wait_for(
            asyncio.gather(share_task(), view_task(), return_exceptions=True),
            timeout=30.0,
        )
    finally:
        share_stop.set()
        view_stop.set()
        capture.shutdown()

    for result in results:
        if isinstance(result, Exception):
            raise result

    assert frames_seen["n"] >= 5
