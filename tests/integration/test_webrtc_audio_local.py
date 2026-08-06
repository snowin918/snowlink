"""Local integration test: two aiortc peers with synthetic Opus audio in-process."""

from __future__ import annotations

import asyncio

import pytest

from snowlink.rtc.audio_receiver import RemoteAudioConsumer
from snowlink.rtc.peer_connection import (
    assert_opus_available,
    create_peer_connection,
    prefer_audio_codec,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.synthetic_audio import SyntheticAudioTrack


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webrtc_audio_local_loopback() -> None:
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    from aiortc import RTCSessionDescription

    assert_opus_available()

    track = SyntheticAudioTrack(
        sample_rate=48_000,
        channels=2,
        frame_ms=20,
        signal="sine",
        frequency_hz=440.0,
        amplitude=0.15,
    )
    sender = create_peer_connection()
    receiver = create_peer_connection()
    consumer = RemoteAudioConsumer(
        sample_rate=48_000,
        channels=2,
        frame_ms=20,
        buffer_target_ms=80,
        expected_frequency_hz=440.0,
        signal="sine",
    )

    try:
        sender.addTrack(track)
        prefer_audio_codec(sender)

        @receiver.on("track")
        def _on_track(remote_track: object) -> None:
            asyncio.get_running_loop().create_task(consumer.start(remote_track))

        receiver.addTransceiver("audio", direction="recvonly")
        prefer_audio_codec(receiver)

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
        while consumer.frames_received < 10:
            if asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.05)

        assert consumer.frames_received >= 10, (
            f"expected >=10 frames, got {consumer.frames_received}; "
            f"ice_sender={sender.iceConnectionState} ice_recv={receiver.iceConnectionState}"
        )
        assert track.frames_generated >= 10
        assert consumer.pts_validator.invalid_pts_count == 0
        tone = consumer.tone.finalize()
        if tone.estimated_frequency_hz is not None:
            assert 420.0 <= tone.estimated_frequency_hz <= 460.0
        # Capacity remains bounded.
        assert consumer.ring.fill_frames() <= consumer.ring.capacity_frames
    finally:
        track.stop()
        await consumer.stop()
        await asyncio.wait_for(sender.close(), timeout=5.0)
        await asyncio.wait_for(receiver.close(), timeout=5.0)


@pytest.mark.asyncio
async def test_opus_preference_in_peer_helpers() -> None:
    pytest.importorskip("aiortc")
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from snowlink.rtc.peer_connection import prefer_audio_codec

    opus = SimpleNamespace(
        mimeType="audio/opus", clockRate=48000, channels=2, sdpFmtpLine=None
    )
    pcmu = SimpleNamespace(
        mimeType="audio/PCMU", clockRate=8000, channels=1, sdpFmtpLine=None
    )
    caps = SimpleNamespace(codecs=[pcmu, opus])
    transceiver = MagicMock()
    transceiver.kind = "audio"
    pc = MagicMock()
    pc.getTransceivers.return_value = [transceiver]
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            selected = prefer_audio_codec(pc)
    assert selected == "opus"
    ordered = transceiver.setCodecPreferences.call_args.args[0]
    assert ordered[0] is opus
