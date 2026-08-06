"""Unit tests for WebRTC metrics helpers and Experiment E results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from snowlink.rtc.models import (
    ExperimentEConfiguration,
    ExperimentEResult,
    TimeoutConfig,
)
from snowlink.rtc.results import result_filename, sanitize_filename_component, write_result
from snowlink.rtc.webrtc_metrics import (
    SequenceTracker,
    estimate_clock_offset_ms,
    fps_from_count,
    parse_rtc_stats_report,
)


def test_sequence_tracker_missing_duplicate_ooo() -> None:
    tracker = SequenceTracker()
    tracker.observe(1)
    tracker.observe(2)
    tracker.observe(5)  # missing 3,4
    tracker.observe(5)  # duplicate
    tracker.observe(4)  # out of order
    assert tracker.missing_sequences == 2
    assert tracker.duplicate_sequences == 1
    assert tracker.out_of_order_sequences == 1
    assert tracker.frames_received == 5


def test_fps_from_count() -> None:
    assert fps_from_count(300, 10.0) == 30.0
    assert fps_from_count(10, 0.0) is None


def test_estimate_clock_offset() -> None:
    # Perfect sync, 10ms one-way delay both directions → offset≈0, uncertainty≈RTT/2.
    samples = [(0.0, 0.010, 0.010, 0.020)]
    offset, unc = estimate_clock_offset_ms(samples)
    assert offset is not None
    assert abs(offset) < 0.01
    assert unc is not None
    assert 9.0 <= unc <= 11.0


def test_parse_rtc_stats_missing_fields_safe() -> None:
    parsed = parse_rtc_stats_report(None)
    assert parsed.network.bytes_sent is None
    parsed2 = parse_rtc_stats_report(
        {
            "1": {
                "id": "1",
                "type": "inbound-rtp",
                "bytesReceived": 1000,
                "packetsLost": 2,
                "jitter": 0.004,
                "framesDecoded": 50,
            }
        }
    )
    assert parsed2.network.bytes_received == 1000
    assert parsed2.network.packets_lost == 2
    assert parsed2.network.jitter_ms == 4.0
    assert parsed2.video.frames_decoded == 50


def test_safe_result_filenames(tmp_path: Path) -> None:
    assert ".." not in sanitize_filename_component("../evil/name")
    assert "/" not in sanitize_filename_component("a/b\\c")
    name = result_filename(
        role="receiver",
        session_name="vpn-on-on",
        when=datetime(2026, 8, 6, 18, 0, 0, tzinfo=UTC),
    )
    assert name == "2026-08-06T180000_receiver_vpn-on-on.json"
    result = ExperimentEResult(
        role="receiver",
        success=True,
        session_name="vpn-on-on",
        configuration=ExperimentEConfiguration(
            role="receiver",
            width=1280,
            height=720,
            fps=30,
            duration_s=120,
            signaling_port=3848,
            timeouts=TimeoutConfig(),
        ),
    )
    path = write_result(result, tmp_path, filename="../../escape.json")
    assert path.parent == tmp_path
    assert path.name == "escape.json"
    assert path.is_file()
