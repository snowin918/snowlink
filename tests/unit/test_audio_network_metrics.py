"""Unit tests for Experiment F tone / network metric helpers."""

from __future__ import annotations

import math

import numpy as np

from snowlink.rtc.audio_metrics import (
    PtsValidator,
    ToneAnalyzer,
    count_clipping,
    estimate_dominant_frequency_hz,
)
from snowlink.rtc.models import ExperimentFResult
from snowlink.rtc.results import result_filename, sanitize_filename_component
from snowlink.rtc.webrtc_metrics import parse_rtc_stats_report


def _sine(freq: float, *, rate: int = 48_000, seconds: float = 0.25, amp: float = 0.15):
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float32) / float(rate)
    mono = (amp * np.sin(2.0 * math.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_tone_frequency_estimation() -> None:
    frames = _sine(440.0)
    est = estimate_dominant_frequency_hz(frames, sample_rate=48_000)
    assert est is not None
    assert 430.0 <= est <= 450.0


def test_rms_and_peak_calculations() -> None:
    analyzer = ToneAnalyzer(sample_rate=48_000, expected_frequency_hz=440.0)
    frames = _sine(440.0, amp=0.15)
    analyzer.observe(frames)
    stats = analyzer.finalize()
    assert stats.rms_average is not None
    assert 0.05 < stats.rms_average < 0.2
    assert stats.peak is not None
    assert 0.1 < stats.peak <= 0.16
    assert stats.estimated_frequency_hz is not None
    assert 430.0 <= stats.estimated_frequency_hz <= 450.0


def test_clipping_detection() -> None:
    frames = np.full((100, 2), 1.0, dtype=np.float32)
    assert count_clipping(frames) == 200
    quiet = np.full((100, 2), 0.1, dtype=np.float32)
    assert count_clipping(quiet) == 0


def test_pts_validator_detects_decreasing() -> None:
    v = PtsValidator(expected_step=960)
    v.observe(0)
    v.observe(960)
    v.observe(900)
    assert v.invalid_pts_count == 1


def test_candidate_and_metrics_serialization() -> None:
    result = ExperimentFResult(role="receiver", session_name="vpn-on-on", success=True)
    result.audio.frames_received = 10
    result.network.current_rtt_ms = 7.0
    result.buffer.underruns = 1
    data = result.to_dict()
    assert data["experiment"] == "experiment_f_webrtc_audio"
    assert data["audio"]["frames_received"] == 10
    assert data["network"]["current_rtt_ms"] == 7.0
    assert data["buffer"]["underruns"] == 1


def test_result_filename_safety() -> None:
    name = result_filename(role="receiver", session_name="vpn on/on..ok")
    assert ".." not in name
    assert "/" not in name
    assert name.endswith(".json")
    assert sanitize_filename_component("../x") == "x"


def test_parse_audio_stats_optional_fields() -> None:
    report = {
        "a": {
            "id": "a",
            "type": "inbound-rtp",
            "kind": "audio",
            "bytesReceived": 1000,
            "packetsReceived": 50,
            "packetsLost": 1,
            "jitter": 0.003,
            "audioLevel": 0.1,
            "concealedSamples": 12,
            "jitterBufferDelay": 0.5,
            "jitterBufferEmittedCount": 100,
        },
        "c": {"id": "c", "type": "codec", "mimeType": "audio/opus", "payloadType": 111},
    }
    parsed = parse_rtc_stats_report(report)
    assert parsed.network.bytes_received == 1000
    assert parsed.network.packets_lost == 1
    assert parsed.audio.get("codec") == "audio/opus"
    assert parsed.audio.get("concealed_samples") == 12
    assert parsed.audio.get("jitter_buffer_delay_ms") == 5.0
