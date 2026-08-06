#!/usr/bin/env python3
"""Experiment F — synthetic WebRTC Opus audio between two computers (aiortc).

Phase 0 validation only. Experiment-only signaling (no production auth).
No WASAPI loopback capture, DXcam, combined A/V, production pairing, or PySide6 UI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.rtc.errors import WebRTCError, format_failure_human  # noqa: E402
from snowlink.rtc.models import (  # noqa: E402
    DEFAULT_AUDIO_AMPLITUDE,
    DEFAULT_AUDIO_CHANNELS,
    DEFAULT_AUDIO_FRAME_MS,
    DEFAULT_AUDIO_GAIN,
    DEFAULT_AUDIO_PORT,
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_BUFFER_TARGET_MS,
    DEFAULT_DURATION_S,
    DEFAULT_PULSE_INTERVAL_MS,
    DEFAULT_TONE_FREQUENCY_HZ,
    ExperimentFConfiguration,
    ExperimentFTimeoutConfig,
    validate_audio_webrtc_configuration,
)
from snowlink.rtc.results import write_result  # noqa: E402
from snowlink.rtc.session_audio import (  # noqa: E402
    PLAYBACK_VOLUME_WARNING,
    run_audio_receiver,
    run_audio_sender,
)
from snowlink.rtc.signaling import SIGNALING_WARNING  # noqa: E402

DEFAULT_RESULTS_DIR = Path("experiment-results") / "experiment-f"

GUIDE_TEXT = f"""
Snowlink Experiment F - synthetic WebRTC Opus audio (aiortc)
===========================================================

Purpose
-------
Validate aiortc Opus audio, 48 kHz / 20 ms frames, sample-driven PTS, host ICE,
LAN UDP connectivity, bounded receiver buffering, and remote playback between
two Windows 11 PCs (including with both VPNs on).

This uses a *synthetic* audio track - not microphone or system-audio capture.

{SIGNALING_WARNING}

{PLAYBACK_VOLUME_WARNING}

Dependencies
------------
  pip install -e ".[dev,webrtc]"
  # For audible playback also install:
  pip install -e ".[audio]"

Finding physical LAN IPv4 addresses
-----------------------------------
On each PC:

  python experiments/experiment_a_adapter_bind.py list

Choose a PREFERRED physical_ethernet or physical_wifi private IPv4.
Do not use VPN / Hyper-V / WSL / loopback addresses for the primary path.

Roles
-----
* Computer A (sender): runs signaling bound to its physical LAN IPv4 and sends
  synthetic Opus audio (default 440 Hz sine at 15% amplitude).
* Computer B (receiver): connects to A's LAN IP, receives audio, optionally plays.

Same-computer validation (two processes, no playback)
-----------------------------------------------------
Terminal A:

  python experiments/experiment_f_webrtc_audio.py send `
    --bind-ip <LOCAL_LAN_IP> `
    --port 3849 `
    --tone-frequency 440 `
    --duration 60

Terminal B:

  python experiments/experiment_f_webrtc_audio.py receive `
    --remote-ip <LOCAL_LAN_IP> `
    --port 3849 `
    --source-ip <LOCAL_LAN_IP> `
    --no-playback `
    --duration 60

Same-computer with low-gain playback
------------------------------------
  python experiments/experiment_f_webrtc_audio.py receive `
    --remote-ip <LOCAL_LAN_IP> `
    --port 3849 `
    --source-ip <LOCAL_LAN_IP> `
    --playback-device default `
    --gain 0.15 `
    --duration 30

Two computers, VPNs off then both VPNs on
-----------------------------------------
Computer A:

  python experiments/experiment_f_webrtc_audio.py send `
    --bind-ip <COMPUTER_A_LAN_IP> `
    --port 3849 `
    --tone-frequency 440 `
    --duration 120 `
    --session-name vpn-on-on

Computer B:

  python experiments/experiment_f_webrtc_audio.py receive `
    --remote-ip <COMPUTER_A_LAN_IP> `
    --port 3849 `
    --source-ip <COMPUTER_B_LAN_IP> `
    --playback-device default `
    --gain 0.20 `
    --duration 120 `
    --session-name vpn-on-on

10-minute no-playback benchmark (Computer B)
--------------------------------------------
  python experiments/experiment_f_webrtc_audio.py receive `
    --remote-ip <COMPUTER_A_LAN_IP> `
    --port 3849 `
    --source-ip <COMPUTER_B_LAN_IP> `
    --no-playback `
    --duration 600 `
    --json

Signal modes
------------
  --signal sine          (default) continuous tone
  --signal silence       all-zero PCM (PTS still advances)
  --signal pulse         periodic click every --pulse-interval-ms
  --signal alternating   500 ms tone / 500 ms silence

What to confirm (pass)
----------------------
* Opus is listed and selected (not PCMU/PCMA).
* ICE reaches connected/completed.
* Selected candidate pair uses the intended physical LAN IPs (or mismatch reported).
* Received sample rate is 48 kHz; PTS errors are zero (or near-zero gaps only).
* For sine mode, estimated frequency is near 440 Hz (e.g. 435-445).
* Buffer stays bounded; underruns/overruns are recorded, not unbounded growth.
* Clean shutdown on duration / Ctrl+C.
* Results under experiment-results/experiment-f/

Identifying the selected ICE candidate pair
-------------------------------------------
Results JSON fields:
  connection.selected_local_candidate
  connection.selected_remote_candidate
  connection.candidate_matches_requested_lan_ip

Latency note
------------
Do not subtract monotonic timestamps across machines. Use WebRTC RTT,
jitter-buffer delay (when available), and "local receiver buffering delay"
(queue depth). That local queue delay is NOT full end-to-end latency.
"""


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _emit_result(result: Any, args: argparse.Namespace, *, write_file: bool) -> Path | None:
    path: Path | None = None
    if write_file:
        path = write_result(result, Path(args.results_dir))
    if args.json:
        _print_json(result.to_dict())
    else:
        status = "PASS" if result.success else "FAIL"
        print(f"Experiment F {status}  role={result.role}")
        cfg = result.configuration
        if cfg is not None:
            print(
                f"  signal={cfg.signal} freq={cfg.tone_frequency_hz} "
                f"rate={cfg.sample_rate} ch={cfg.channels} "
                f"frame_ms={cfg.frame_duration_ms} codec={result.audio.codec} "
                f"duration={cfg.duration_s}s session={result.session_name}"
            )
        conn = result.connection
        print(
            f"  ice={conn.ice_state} peer={conn.peer_state} signaling={conn.signaling_state}"
        )
        local = conn.selected_local_candidate
        remote = conn.selected_remote_candidate
        if local and local.ip:
            print(
                f"  selected_local={local.ip}:{local.port} "
                f"{local.protocol}/{local.type} category={local.adapter_category}"
            )
        if remote and remote.ip:
            print(
                f"  selected_remote={remote.ip}:{remote.port} "
                f"{remote.protocol}/{remote.type}"
            )
        if conn.candidate_matches_requested_lan_ip is not None:
            print(
                f"  candidate_matches_requested_lan_ip="
                f"{conn.candidate_matches_requested_lan_ip}"
            )
        audio = result.audio
        print(
            f"  frames_gen={audio.frames_generated} recv={audio.frames_received} "
            f"samples_recv={audio.samples_received} "
            f"invalid_pts={audio.invalid_pts_count}"
        )
        if audio.estimated_frequency_hz is not None:
            print(
                f"  estimated_freq_hz={audio.estimated_frequency_hz:.1f} "
                f"rms={audio.rms_average} peak={audio.peak}"
            )
        buf = result.buffer
        print(
            f"  buffer_avg_ms={buf.average_fill_ms} peak_ms={buf.peak_fill_ms} "
            f"underruns={buf.underruns} overruns={buf.overruns} "
            f"local_receiver_buffering_delay_ms={buf.local_receiver_buffering_delay_ms}"
        )
        if result.network.current_rtt_ms is not None:
            print(
                f"  rtt_ms={result.network.current_rtt_ms:.2f} "
                f"jitter_ms={result.network.jitter_ms} "
                f"packets_lost={result.network.packets_lost}"
            )
        if result.resources.cpu_percent_average is not None:
            print(
                f"  cpu_avg={result.resources.cpu_percent_average:.1f}% "
                f"cpu_peak={result.resources.cpu_percent_peak} "
                f"mem_peak_mb={result.resources.memory_mb_peak}"
            )
        for w in result.warnings:
            print(f"  warning: {w}")
        for err in result.errors:
            if isinstance(err, dict):
                print()
                from snowlink.rtc.errors import WebRTCFailure

                failure = WebRTCFailure(
                    code=str(err.get("code", "UNEXPECTED_WEBRTC_AUDIO_ERROR")),
                    message=str(err.get("message", "")),
                    likely_cause=str(err.get("likely_cause", "")),
                    suggested_next_step=str(err.get("suggested_next_step", "")),
                    exception_type=err.get("exception_type"),
                    signaling_state=err.get("signaling_state"),
                    ice_state=err.get("ice_state"),
                    peer_state=err.get("peer_state"),
                )
                print(format_failure_human(failure))
        if path is not None:
            print(f"  result_file={path}")
    return path


def _timeouts_from_args(args: argparse.Namespace) -> ExperimentFTimeoutConfig:
    return ExperimentFTimeoutConfig(
        signaling_connect_s=float(args.signaling_timeout),
        offer_answer_s=float(args.offer_answer_timeout),
        ice_gathering_s=float(args.ice_gathering_timeout),
        ice_connection_s=float(args.ice_timeout),
        remote_track_s=float(args.remote_track_timeout),
        first_frame_s=float(args.first_frame_timeout),
        inactivity_s=float(args.inactivity_timeout),
        shutdown_s=float(args.shutdown_timeout),
    )


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_AUDIO_PORT)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_AUDIO_SAMPLE_RATE)
    parser.add_argument("--channels", type=int, default=DEFAULT_AUDIO_CHANNELS)
    parser.add_argument("--frame-ms", type=int, default=DEFAULT_AUDIO_FRAME_MS)
    parser.add_argument(
        "--signal",
        choices=["sine", "silence", "pulse", "alternating"],
        default="sine",
    )
    parser.add_argument("--tone-frequency", type=float, default=DEFAULT_TONE_FREQUENCY_HZ)
    parser.add_argument("--amplitude", type=float, default=DEFAULT_AUDIO_AMPLITUDE)
    parser.add_argument("--pulse-interval-ms", type=int, default=DEFAULT_PULSE_INTERVAL_MS)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--session-name", default="unnamed")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory for JSON result files (gitignored)",
    )
    parser.add_argument("--signaling-timeout", type=float, default=5.0)
    parser.add_argument("--offer-answer-timeout", type=float, default=10.0)
    parser.add_argument("--ice-gathering-timeout", type=float, default=10.0)
    parser.add_argument("--ice-timeout", type=float, default=20.0)
    parser.add_argument("--remote-track-timeout", type=float, default=15.0)
    parser.add_argument("--first-frame-timeout", type=float, default=10.0)
    parser.add_argument("--inactivity-timeout", type=float, default=5.0)
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)


def cmd_guide(_args: argparse.Namespace) -> int:
    print(GUIDE_TEXT.strip() + "\n")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    try:
        validate_audio_webrtc_configuration(
            sample_rate=args.sample_rate,
            channels=args.channels,
            frame_ms=args.frame_ms,
            duration_s=args.duration,
            port=args.port,
            amplitude=args.amplitude,
            gain=DEFAULT_AUDIO_GAIN,
            tone_frequency_hz=args.tone_frequency,
        )
    except ValueError as exc:
        print(f"INVALID_CONFIGURATION: {exc}", file=sys.stderr)
        return 2

    config = ExperimentFConfiguration(
        role="sender",
        duration_s=args.duration,
        signaling_port=args.port,
        sample_rate=args.sample_rate,
        channels=args.channels,
        frame_duration_ms=args.frame_ms,
        signal=args.signal,
        tone_frequency_hz=args.tone_frequency,
        amplitude=args.amplitude,
        pulse_interval_ms=args.pulse_interval_ms,
        bind_ip=args.bind_ip,
        playback=False,
        session_name=args.session_name,
        timeouts=_timeouts_from_args(args),
    )
    try:
        result = asyncio.run(run_audio_sender(config))
    except WebRTCError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    _emit_result(result, args, write_file=True)
    return 0 if result.success else 1


def cmd_receive(args: argparse.Namespace) -> int:
    try:
        validate_audio_webrtc_configuration(
            sample_rate=args.sample_rate,
            channels=args.channels,
            frame_ms=args.frame_ms,
            duration_s=args.duration,
            port=args.port,
            amplitude=DEFAULT_AUDIO_AMPLITUDE,
            gain=args.gain,
            tone_frequency_hz=args.tone_frequency,
        )
    except ValueError as exc:
        print(f"INVALID_CONFIGURATION: {exc}", file=sys.stderr)
        return 2

    config = ExperimentFConfiguration(
        role="receiver",
        duration_s=args.duration,
        signaling_port=args.port,
        sample_rate=args.sample_rate,
        channels=args.channels,
        frame_duration_ms=args.frame_ms,
        signal=args.signal,
        tone_frequency_hz=args.tone_frequency,
        amplitude=DEFAULT_AUDIO_AMPLITUDE,
        pulse_interval_ms=args.pulse_interval_ms,
        remote_ip=args.remote_ip,
        requested_source_ip=args.source_ip,
        playback=not args.no_playback,
        playback_device=args.playback_device,
        gain=args.gain,
        muted=args.muted,
        buffer_target_ms=args.buffer_target_ms,
        session_name=args.session_name,
        timeouts=_timeouts_from_args(args),
    )
    try:
        result = asyncio.run(run_audio_receiver(config))
    except WebRTCError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    _emit_result(result, args, write_file=True)
    return 0 if result.success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experiment F: synthetic WebRTC Opus audio (aiortc)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_guide = sub.add_parser("guide", help="Print two-computer test instructions")
    p_guide.set_defaults(func=cmd_guide)

    p_send = sub.add_parser("send", help="Run sender (signaling + synthetic audio)")
    p_send.add_argument("--bind-ip", required=True, help="Physical LAN IPv4 to bind signaling")
    _add_common_flags(p_send)
    p_send.set_defaults(func=cmd_send)

    p_recv = sub.add_parser("receive", help="Run receiver (connect + optional playback)")
    p_recv.add_argument("--remote-ip", required=True, help="Sender physical LAN IPv4")
    p_recv.add_argument(
        "--source-ip",
        default=None,
        help="Local physical LAN IPv4 for signaling bind (recommended)",
    )
    p_recv.add_argument("--playback-device", default="default")
    p_recv.add_argument("--gain", type=float, default=DEFAULT_AUDIO_GAIN)
    p_recv.add_argument("--muted", action="store_true")
    p_recv.add_argument(
        "--no-playback",
        action="store_true",
        help="Receive and drain audio without WASAPI playback",
    )
    p_recv.add_argument("--buffer-target-ms", type=int, default=DEFAULT_BUFFER_TARGET_MS)
    _add_common_flags(p_recv)
    p_recv.set_defaults(func=cmd_receive)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
