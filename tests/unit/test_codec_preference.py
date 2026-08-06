"""Unit tests for VP8 / Opus codec preference helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from snowlink.rtc.errors import WebRTCError
from snowlink.rtc.peer_connection import (
    assert_opus_available,
    assert_preferred_video_codec_available,
    prefer_audio_codec,
    prefer_video_codec,
)


def _codec(mime: str, *, clock: int = 90000) -> Any:
    return SimpleNamespace(mimeType=mime, clockRate=clock, channels=None, sdpFmtpLine=None)


def test_assert_vp8_available() -> None:
    caps = SimpleNamespace(codecs=[_codec("video/VP8"), _codec("video/H264")])
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            assert (
                assert_preferred_video_codec_available(prefer="video/VP8") == "VP8"
            )


def test_assert_vp8_unavailable_no_fallback() -> None:
    caps = SimpleNamespace(codecs=[_codec("video/H264")])
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            with pytest.raises(WebRTCError) as exc:
                assert_preferred_video_codec_available(prefer="video/VP8")
            assert exc.value.failure.code == "VP8_UNAVAILABLE"


def test_assert_h264_fallback() -> None:
    caps = SimpleNamespace(codecs=[_codec("video/H264")])
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            assert (
                assert_preferred_video_codec_available(
                    prefer="video/VP8",
                    allow_h264_fallback=True,
                )
                == "H264"
            )


def test_prefer_video_codec_sets_preferences() -> None:
    vp8 = _codec("video/VP8")
    h264 = _codec("video/H264")
    caps = SimpleNamespace(codecs=[h264, vp8])
    transceiver = MagicMock()
    transceiver.kind = "video"
    pc = MagicMock()
    pc.getTransceivers.return_value = [transceiver]
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            selected = prefer_video_codec(pc, prefer="video/VP8")
    assert selected == "VP8"
    transceiver.setCodecPreferences.assert_called_once()
    ordered = transceiver.setCodecPreferences.call_args.args[0]
    assert ordered[0] is vp8


def test_assert_opus_available() -> None:
    caps = SimpleNamespace(
        codecs=[_codec("audio/opus", clock=48000), _codec("audio/PCMU", clock=8000)]
    )
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            assert assert_opus_available() == "opus"


def test_assert_opus_unavailable() -> None:
    caps = SimpleNamespace(codecs=[_codec("audio/PCMU", clock=8000)])
    with patch("snowlink.rtc.peer_connection.require_aiortc"):
        with patch("aiortc.RTCRtpSender") as sender:
            sender.getCapabilities.return_value = caps
            with pytest.raises(WebRTCError) as exc:
                assert_opus_available()
            assert exc.value.failure.code == "OPUS_UNAVAILABLE"


def test_prefer_audio_codec_sets_preferences() -> None:
    opus = _codec("audio/opus", clock=48000)
    pcmu = _codec("audio/PCMU", clock=8000)
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
