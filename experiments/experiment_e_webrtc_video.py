#!/usr/bin/env python3
"""Experiment E — synthetic WebRTC video between two computers (aiortc).

Phase 0 validation only. Experiment-only signaling (no production auth).
No DXcam, system audio, Opus, production pairing, or PySide6 UI.
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
    DEFAULT_DURATION_S,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_PORT,
    DEFAULT_WIDTH,
    ExperimentEConfiguration,
    TimeoutConfig,
    validate_video_configuration,
)
from snowlink.rtc.results import write_result  # noqa: E402
from snowlink.rtc.session import run_receiver, run_sender  # noqa: E402
from snowlink.rtc.signaling import SIGNALING_WARNING  # noqa: E402

DEFAULT_RESULTS_DIR = Path("experiment-results") / "experiment-e"

GUIDE_TEXT = f"""
Snowlink Experiment E - synthetic WebRTC video (aiortc)
=======================================================

Purpose
-------
Validate aiortc VP8 video, offer/answer signaling, host ICE candidates, and
LAN UDP connectivity between two Windows 11 PCs (including with both VPNs on).
This uses a *synthetic* video track - not screen capture.

{SIGNALING_WARNING}

Dependencies
------------
  pip install -e ".[dev,webrtc]"

Finding physical LAN IPv4 addresses
-----------------------------------
On each PC:

  python experiments/experiment_a_adapter_bind.py list

Choose a PREFERRED physical_ethernet or physical_wifi private IPv4.
Do not use VPN / Hyper-V / WSL / loopback addresses for the primary path.

Roles
-----
* Computer A (sender): runs signaling bound to its physical LAN IPv4 and sends
  synthetic VP8 video.
* Computer B (receiver): connects to A's LAN IP, receives and optionally previews.

Same-computer validation (two processes)
----------------------------------------
Terminal A:

  python experiments/experiment_e_webrtc_video.py send `
    --bind-ip 127.0.0.1 `
    --port 3848 `
    --fps 30 `
    --width 1280 `
    --height 720 `
    --duration 30

Terminal B:

  python experiments/experiment_e_webrtc_video.py receive `
    --remote-ip 127.0.0.1 `
    --port 3848 `
    --source-ip 127.0.0.1 `
    --duration 30

Two computers, VPNs off then both VPNs on
-----------------------------------------
Computer A:

  python experiments/experiment_e_webrtc_video.py send `
    --bind-ip <COMPUTER_A_LAN_IP> `
    --port 3848 `
    --fps 30 `
    --width 1280 `
    --height 720 `
    --duration 120 `
    --session-name vpn-on-on

Computer B:

  python experiments/experiment_e_webrtc_video.py receive `
    --remote-ip <COMPUTER_A_LAN_IP> `
    --port 3848 `
    --source-ip <COMPUTER_B_LAN_IP> `
    --duration 120 `
    --session-name vpn-on-on

10-minute headless benchmark (Computer B)
-----------------------------------------
  python experiments/experiment_e_webrtc_video.py receive `
    --remote-ip <COMPUTER_A_LAN_IP> `
    --port 3848 `
    --source-ip <COMPUTER_B_LAN_IP> `
    --duration 600 `
    --no-preview `
    --json

What to confirm
---------------
* Signaling succeeds over the physical LAN TCP path.
* ICE reaches connected/completed.
* Selected candidate pair uses the intended physical LAN IPs (or mismatch is reported).
* Synthetic video is visible (unless --no-preview).
* Received FPS is within ~10% of requested under light load.
* Clean shutdown on duration / Escape / Ctrl+C.
* Results under experiment-results/experiment-e/

Latency note
------------
Do not subtract monotonic timestamps across machines. Use WebRTC RTT, frame
inter-arrival, and a phone-recorded visual timer for manual glass-to-glass checks.
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
        print(f"Experiment E {status}  role={result.role}")
        cfg = result.configuration
        if cfg is not None:
            print(
                f"  {cfg.width}x{cfg.height}@{cfg.fps} codec={result.video.codec} "
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
        print(
            f"  frames_gen={result.video.frames_generated} "
            f"recv={result.video.frames_received} "
            f"rendered={result.video.frames_rendered} "
            f"skipped={result.video.frames_skipped_by_schedule}"
        )
        if result.video.received_fps is not None:
            print(
                f"  received_fps={result.video.received_fps:.2f} "
                f"rendered_fps={result.video.rendered_fps}"
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
                    code=str(err.get("code", "UNEXPECTED_WEBRTC_ERROR")),
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


def _timeouts_from_args(args: argparse.Namespace) -> TimeoutConfig:
    return TimeoutConfig(
        signaling_connect_s=float(args.signaling_timeout),
        offer_answer_s=float(args.offer_answer_timeout),
        ice_gathering_s=float(args.ice_gathering_timeout),
        ice_connection_s=float(args.ice_timeout),
        first_frame_s=float(args.first_frame_timeout),
        inactivity_s=float(args.inactivity_timeout),
        shutdown_s=float(args.shutdown_timeout),
    )


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--session-name", default="unnamed")
    parser.add_argument("--allow-h264-fallback", action="store_true")
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
    parser.add_argument("--first-frame-timeout", type=float, default=15.0)
    parser.add_argument("--inactivity-timeout", type=float, default=30.0)
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)


def cmd_guide(_args: argparse.Namespace) -> int:
    print(GUIDE_TEXT.strip() + "\n")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    try:
        validate_video_configuration(
            width=args.width,
            height=args.height,
            fps=args.fps,
            duration_s=args.duration,
            port=args.port,
        )
    except ValueError as exc:
        print(f"INVALID_CONFIGURATION: {exc}", file=sys.stderr)
        return 2

    config = ExperimentEConfiguration(
        role="sender",
        width=args.width,
        height=args.height,
        fps=args.fps,
        duration_s=args.duration,
        signaling_port=args.port,
        bind_ip=args.bind_ip,
        allow_h264_fallback=args.allow_h264_fallback,
        preview=False,
        session_name=args.session_name,
        timeouts=_timeouts_from_args(args),
    )
    try:
        result = asyncio.run(run_sender(config))
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
        validate_video_configuration(
            width=args.width,
            height=args.height,
            fps=args.fps,
            duration_s=args.duration,
            port=args.port,
        )
    except ValueError as exc:
        print(f"INVALID_CONFIGURATION: {exc}", file=sys.stderr)
        return 2

    config = ExperimentEConfiguration(
        role="receiver",
        width=args.width,
        height=args.height,
        fps=args.fps,
        duration_s=args.duration,
        signaling_port=args.port,
        remote_ip=args.remote_ip,
        requested_source_ip=args.source_ip,
        allow_h264_fallback=args.allow_h264_fallback,
        preview=not args.no_preview,
        session_name=args.session_name,
        timeouts=_timeouts_from_args(args),
    )
    try:
        result = asyncio.run(run_receiver(config))
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
        description="Experiment E: synthetic WebRTC video (aiortc / VP8)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_guide = sub.add_parser("guide", help="Print two-computer test instructions")
    p_guide.set_defaults(func=cmd_guide)

    p_send = sub.add_parser("send", help="Run sender (signaling + synthetic video)")
    p_send.add_argument("--bind-ip", required=True, help="Physical LAN IPv4 to bind signaling")
    _add_common_flags(p_send)
    p_send.set_defaults(func=cmd_send)

    p_recv = sub.add_parser("receive", help="Run receiver (connect + optional preview)")
    p_recv.add_argument("--remote-ip", required=True, help="Sender physical LAN IPv4")
    p_recv.add_argument(
        "--source-ip",
        default=None,
        help="Local physical LAN IPv4 for signaling bind (recommended)",
    )
    p_recv.add_argument(
        "--no-preview",
        action="store_true",
        help="Disable OpenCV preview (headless metrics)",
    )
    _add_common_flags(p_recv)
    p_recv.set_defaults(func=cmd_receive)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
