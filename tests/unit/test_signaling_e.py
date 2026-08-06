"""Unit tests for experiment signaling validation and timeouts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from snowlink.rtc.errors import WebRTCError, failure_for, map_exception
from snowlink.rtc.models import MAX_SIGNALING_BODY_BYTES
from snowlink.rtc.signaling import SignalingServer


async def _start_server(
    handler: Any,
    *,
    max_body_bytes: int = MAX_SIGNALING_BODY_BYTES,
) -> SignalingServer:
    server = SignalingServer(
        bind_ip="127.0.0.1",
        port=0,
        offer_handler=handler,
        max_body_bytes=max_body_bytes,
    )
    await server.start()
    return server


@pytest.mark.asyncio
async def test_signaling_rejects_oversized_body() -> None:
    pytest.importorskip("aiohttp")

    async def handler(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"sdp": "x", "type": "answer"}

    server = await _start_server(handler, max_body_bytes=1024)
    try:
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{server.port}/offer",
                data=b"x" * 2048,
                headers={"Content-Type": "application/json"},
            ) as resp:
                assert resp.status == 413
                data = await resp.json()
                assert data.get("code") == "MALFORMED_SDP"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_signaling_rejects_malformed_sdp() -> None:
    pytest.importorskip("aiohttp")

    async def handler(_payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("handler should not be called")

    server = await _start_server(handler)
    try:
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{server.port}/offer",
                json={"sdp": "", "type": "offer"},
            ) as resp:
                assert resp.status == 400
                data = await resp.json()
                assert data.get("code") == "MALFORMED_SDP"

            async with session.post(
                f"http://127.0.0.1:{server.port}/offer",
                json={"sdp": "v=0", "type": "answer"},
            ) as resp:
                assert resp.status == 400
                data = await resp.json()
                assert data.get("code") == "MALFORMED_SDP"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_signaling_accepts_only_one_receiver() -> None:
    pytest.importorskip("aiohttp")
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_payload: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"sdp": "v=0", "type": "answer"}

    server = await _start_server(handler)
    try:
        from aiohttp import ClientSession

        async with ClientSession() as session:
            task = asyncio.create_task(
                session.post(
                    f"http://127.0.0.1:{server.port}/offer",
                    json={"sdp": "v=0", "type": "offer"},
                )
            )
            await started.wait()
            async with session.post(
                f"http://127.0.0.1:{server.port}/offer",
                json={"sdp": "v=0", "type": "offer"},
            ) as resp:
                assert resp.status == 409
                data = await resp.json()
                assert data.get("code") == "OFFER_REJECTED"
            release.set()
            first = await task
            assert first.status == 200
            first.release()
    finally:
        await server.close()


def test_timeout_error_mapping() -> None:
    failure = map_exception(TimeoutError("timed out"))
    assert failure.code == "SIGNALING_TIMEOUT"
    wrapped = WebRTCError(failure_for("ICE_CONNECTION_FAILED", "ice failed"))
    assert map_exception(wrapped).code == "ICE_CONNECTION_FAILED"


def test_max_signaling_body_constant() -> None:
    assert MAX_SIGNALING_BODY_BYTES >= 64 * 1024
