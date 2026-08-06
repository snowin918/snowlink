"""Local integration test: two aiortc peers with synthetic video in-process."""

from __future__ import annotations

import asyncio

import pytest

from snowlink.rtc.peer_connection import (
    create_peer_connection,
    prefer_video_codec,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.preview import RemoteVideoConsumer
from snowlink.rtc.synthetic_video import SyntheticVideoTrack


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webrtc_video_local_loopback() -> None:
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    from aiortc import RTCSessionDescription

    track = SyntheticVideoTrack(width=160, height=90, fps=15)
    sender = create_peer_connection()
    receiver = create_peer_connection()
    consumer = RemoteVideoConsumer()
    frames_ok = False

    try:
        sender.addTrack(track)
        prefer_video_codec(sender, prefer="video/VP8")

        @receiver.on("track")
        def _on_track(remote_track: object) -> None:
            asyncio.get_running_loop().create_task(consumer.start(remote_track))

        receiver.addTransceiver("video", direction="recvonly")
        prefer_video_codec(receiver, prefer="video/VP8")

        offer = await receiver.createOffer()
        await receiver.setLocalDescription(offer)
        await wait_ice_gathering_complete(receiver, timeout_s=10.0)

        assert receiver.localDescription is not None
        await sender.setRemoteDescription(
            RTCSessionDescription(
                sdp=receiver.localDescription.sdp,
                type=receiver.localDescription.type,
            )
        )
        answer = await sender.createAnswer()
        await sender.setLocalDescription(answer)
        await wait_ice_gathering_complete(sender, timeout_s=10.0)

        assert sender.localDescription is not None
        await receiver.setRemoteDescription(
            RTCSessionDescription(
                sdp=sender.localDescription.sdp,
                type=sender.localDescription.type,
            )
        )

        await wait_ice_connected(sender, timeout_s=20.0)
        await wait_ice_connected(receiver, timeout_s=20.0)

        deadline = asyncio.get_running_loop().time() + 10.0
        while consumer.frames_received < 5:
            if asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.05)

        frames_ok = consumer.frames_received >= 5
        assert frames_ok, (
            f"expected >=5 frames, got {consumer.frames_received}; "
            f"ice_sender={sender.iceConnectionState} ice_recv={receiver.iceConnectionState}"
        )
        assert track.frames_generated >= 5
        assert consumer.slot.pending_count() <= 1
    finally:
        track.stop()
        await consumer.stop()
        await asyncio.wait_for(sender.close(), timeout=5.0)
        await asyncio.wait_for(receiver.close(), timeout=5.0)


@pytest.mark.asyncio
async def test_clean_async_shutdown_signaling_only() -> None:
    pytest.importorskip("aiohttp")
    from snowlink.rtc.signaling import SignalingServer

    async def handler(payload: dict[str, object]) -> dict[str, object]:
        _ = payload
        return {"sdp": "v=0", "type": "answer"}

    server = SignalingServer(bind_ip="127.0.0.1", port=0, offer_handler=handler)
    await server.start()
    assert server.port > 0
    await server.close()
    await server.close()
