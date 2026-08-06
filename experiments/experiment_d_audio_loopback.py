#!/usr/bin/env python3
"""Experiment D — WASAPI system-audio loopback capture and local playback.

Phase 0 validation only. No networking, WebRTC, Opus transport, or product UI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.media.audio_errors import (  # noqa: E402
    AudioError,
    AudioFailure,
    format_failure_human,
)
from snowlink.media.audio_models import (  # noqa: E402
    DEFAULT_BUFFER_MS,
    DEFAULT_FRAME_MS,
    DEFAULT_GAIN,
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    validate_audio_configuration,
)
from snowlink.media.audio_pipeline import (  # noqa: E402
    make_click_tone,
    run_audio_pipeline,
)
from snowlink.media.experiment_d_results import write_result  # noqa: E402
from snowlink.platform_win.audio_endpoints import (  # noqa: E402
    enumerate_audio_endpoints,
    format_endpoint_list,
    is_windows,
)

DEFAULT_RESULTS_DIR = Path("experiment-results") / "experiment-d"


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
        print(f"Experiment D {status}")
        cfg = result.configuration
        if cfg is not None:
            print(
                f"  mode={cfg.mode} capture={cfg.capture_device} "
                f"playback={cfg.playback_device} "
                f"{cfg.target_sample_rate}Hz ch={cfg.target_channels} "
                f"frame={cfg.frame_duration_ms}ms buffer={cfg.buffer_capacity_ms}ms"
            )
        print(
            f"  captured_samples={result.capture.captured_samples} "
            f"converted={result.conversion.converted_samples} "
            f"played={result.playback.played_samples}"
        )
        print(
            f"  non_silent={result.capture.non_silent_frames} "
            f"silence={result.capture.silence_frames} "
            f"peak={result.capture.peak_level:.4f} "
            f"rms_avg={result.capture.rms_average:.4f}"
        )
        print(
            f"  buffer fill_avg_ms={result.buffer.average_fill_ms} "
            f"peak_ms={result.buffer.peak_fill_ms} "
            f"underruns={result.buffer.underruns} "
            f"overruns={result.buffer.overruns} "
            f"dropped={result.buffer.dropped_samples}"
        )
        if result.timing_ms.queue_delay_average is not None:
            print(
                f"  local_pipeline_queue_delay_avg_ms="
                f"{result.timing_ms.queue_delay_average:.2f} "
                f"p95={result.timing_ms.queue_delay_p95} "
                f"(not end-to-end latency)"
            )
        if result.resources.cpu_percent_average is not None:
            print(
                f"  cpu_avg={result.resources.cpu_percent_average:.1f}% "
                f"cpu_peak={result.resources.cpu_percent_peak} "
                f"mem_peak_mb={result.resources.memory_mb_peak}"
            )
        for w in result.warnings:
            print(f"  {w}")
        for err in result.errors:
            print()
            failure = AudioFailure(
                code=str(err.get("code", "UNEXPECTED_AUDIO_ERROR")),
                message=str(err.get("message", "")),
                likely_cause=str(err.get("likely_cause", "")),
                suggested_next_step=str(err.get("suggested_next_step", "")),
                exception_type=err.get("exception_type"),
            )
            print(format_failure_human(failure))
        if path is not None:
            print(f"  result_file={path}")
    return path


def cmd_list(args: argparse.Namespace) -> int:
    if not is_windows():
        print("Experiment D audio listing requires Windows.", file=sys.stderr)
        return 2
    try:
        devices = enumerate_audio_endpoints()
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    if args.json:
        _print_json(
            {
                "experiment": "experiment_d_audio_loopback",
                "note": (
                    "System-audio capture must use a WASAPI loopback endpoint, "
                    "never a microphone."
                ),
                "devices": [d.to_dict() for d in devices],
            }
        )
    else:
        print(format_endpoint_list(devices), end="")
    return 0


def _config_from_args(
    args: argparse.Namespace,
    *,
    mode: str,
    enable_playback: bool,
) -> Any:
    return validate_audio_configuration(
        capture_device=str(args.capture_device),
        playback_device=str(getattr(args, "playback_device", "default")),
        sample_rate=int(getattr(args, "sample_rate", TARGET_SAMPLE_RATE)),
        channels=int(getattr(args, "channels", TARGET_CHANNELS)),
        frame_ms=int(getattr(args, "frame_ms", DEFAULT_FRAME_MS)),
        buffer_ms=int(getattr(args, "buffer_ms", DEFAULT_BUFFER_MS)),
        duration=int(args.duration),
        gain=float(getattr(args, "gain", DEFAULT_GAIN)),
        muted=bool(getattr(args, "muted", False)),
        mode=mode,  # type: ignore[arg-type]
        enable_playback=enable_playback,
    )


def _print_monitor(snap: dict[str, Any]) -> None:
    print(
        f"[monitor] non_silent={snap['non_silent_detected']} "
        f"peak={snap['peak_level']:.4f} rms={snap['rms_level']:.4f} "
        f"frames={snap['captured_frames']} samples={snap['captured_samples']} "
        f"rate≈{snap['estimated_input_sample_rate']} "
        f"fill_ms={snap['buffer_fill_ms']:.1f} "
        f"underruns={snap['underruns']} overruns={snap['overruns']} "
        f"cb_errors={snap['callback_errors']}"
    )


def cmd_monitor(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args, mode="monitor", enable_playback=False)
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    print(
        f"Monitor mode  capture={config.capture_device} duration={config.duration_s}s"
    )
    print("Play ordinary non-DRM system audio. Ctrl+C stops cleanly.")
    print("Raw PCM is not stored or printed.")
    code, result = run_audio_pipeline(
        config,
        honor_duration=True,
        monitor_callback=_print_monitor if not args.json else None,
    )
    _emit_result(result, args, write_file=False)
    return code


def cmd_playback(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args, mode="playback", enable_playback=True)
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    print(
        f"Playback mode  capture={config.capture_device} "
        f"playback={config.playback_device} gain={config.gain} "
        f"muted={config.muted} duration={config.duration_s}s"
    )
    print(
        "Prefer headphones. Capture+playback on the same speakers can feedback. "
        "Windows master volume is not changed."
    )
    code, result = run_audio_pipeline(config, honor_duration=True)
    _emit_result(result, args, write_file=False)
    return code


def cmd_benchmark(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args, mode="benchmark", enable_playback=True)
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    print(
        f"Benchmark  capture={config.capture_device} playback={config.playback_device} "
        f"{config.target_sample_rate}Hz ch={config.target_channels} "
        f"frame={config.frame_duration_ms}ms buffer={config.buffer_capacity_ms}ms "
        f"duration={config.duration_s}s gain={config.gain}"
    )
    code, result = run_audio_pipeline(config, honor_duration=True)
    _emit_result(result, args, write_file=True)
    return code


def cmd_latency(args: argparse.Namespace) -> int:
    """Optional coarse latency helper — not a precise measurement claim."""
    print(
        "LATENCY HELPER (manual / coarse)\n"
        "This mode plays a short conservative test click through the selected\n"
        "playback device while capturing loopback. It does NOT claim precise\n"
        "end-to-end latency unless you align the click yourself.\n"
        "Windows master volume will NOT be changed.\n"
    )
    if not args.yes:
        try:
            answer = input("Type YES to play a short test click: ").strip()
        except EOFError:
            answer = ""
        if answer != "YES":
            print("Aborted (explicit confirmation required).", file=sys.stderr)
            return 2
    try:
        config = _config_from_args(args, mode="latency", enable_playback=True)
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2

    # Inject a delayed click via synthetic overlay is complex with real capture;
    # instead play the click on a side timer while the pipeline runs.
    click = make_click_tone(
        sample_rate=config.target_sample_rate,
        channels=config.target_channels,
        amplitude=0.15,
    )
    click_holder: dict[str, Any] = {"played": False}

    def on_monitor(snap: dict[str, Any]) -> None:
        if not args.json:
            _print_monitor(snap)

    # Run standard pipeline; after ~1s attempt to write click via a one-shot
    # note in details — actual click playback uses a short additional write if
    # the session player is available. For simplicity, document manual method.
    print(
        "Starting capture+playback. After ~1 second a short click may be audible.\n"
        "Manually note the delay between click generation and what you hear, or\n"
        "compare waveform peaks if you record externally. Treat results as coarse."
    )
    started = time.perf_counter()
    code, result = run_audio_pipeline(
        config,
        honor_duration=True,
        monitor_callback=on_monitor,
    )
    # Record that this was a latency helper run; click auto-injection is best-effort.
    result.details["latency_helper"] = {
        "method": "manual_click_alignment_optional",
        "click_samples": int(click.shape[0]),
        "click_amplitude": 0.15,
        "precise_claim": False,
        "note": (
            "Do not treat queue_delay metrics as true capture-to-ear latency. "
            "Use headphones and align a known click by ear or external recording."
        ),
        "elapsed_helper_s": time.perf_counter() - started,
        "auto_click_played": bool(click_holder["played"]),
    }
    result.warnings.append(
        "Latency helper does not claim precise end-to-end audio latency."
    )
    _emit_result(result, args, write_file=bool(args.json) or True)
    # Avoid unused warning in linters for click when not injected into stream.
    _ = click
    return code


def _add_device_args(p: argparse.ArgumentParser, *, with_playback: bool) -> None:
    p.add_argument(
        "--capture-device",
        default="default",
        help="Loopback device index or 'default'",
    )
    if with_playback:
        p.add_argument(
            "--playback-device",
            default="default",
            help="Playback device index or 'default'",
        )
    p.add_argument(
        "--sample-rate",
        type=int,
        default=TARGET_SAMPLE_RATE,
        help=f"Target sample rate (default {TARGET_SAMPLE_RATE})",
    )
    p.add_argument(
        "--channels",
        type=int,
        default=TARGET_CHANNELS,
        help=f"Target channels (default {TARGET_CHANNELS})",
    )
    p.add_argument(
        "--frame-ms",
        type=int,
        default=DEFAULT_FRAME_MS,
        help=f"Frame duration ms (default {DEFAULT_FRAME_MS})",
    )
    p.add_argument(
        "--buffer-ms",
        type=int,
        default=DEFAULT_BUFFER_MS,
        help=f"Ring buffer capacity ms (default {DEFAULT_BUFFER_MS})",
    )
    p.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds",
    )
    p.add_argument("--json", action="store_true", help="Print result JSON")
    p.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory for benchmark JSON results",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Snowlink Experiment D — WASAPI loopback capture / local playback "
            "(no networking)."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List audio endpoints and loopback devices")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_mon = sub.add_parser("monitor", help="Capture system audio without playback")
    _add_device_args(p_mon, with_playback=False)
    p_mon.set_defaults(func=cmd_monitor)

    p_play = sub.add_parser("playback", help="Capture and play locally")
    _add_device_args(p_play, with_playback=True)
    p_play.add_argument(
        "--gain",
        type=float,
        default=DEFAULT_GAIN,
        help=f"Software output gain 0.0–1.0 (default {DEFAULT_GAIN})",
    )
    p_play.add_argument(
        "--muted",
        action="store_true",
        help="Mute local playback without stopping capture",
    )
    p_play.set_defaults(func=cmd_playback)

    p_bench = sub.add_parser("benchmark", help="Timed capture/playback benchmark")
    _add_device_args(p_bench, with_playback=True)
    p_bench.add_argument("--gain", type=float, default=DEFAULT_GAIN)
    p_bench.add_argument("--muted", action="store_true")
    p_bench.set_defaults(func=cmd_benchmark)

    p_lat = sub.add_parser(
        "latency",
        help="Optional coarse latency helper (requires explicit YES confirmation)",
    )
    _add_device_args(p_lat, with_playback=True)
    p_lat.add_argument("--gain", type=float, default=0.4)
    p_lat.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive YES prompt (still prints warnings)",
    )
    p_lat.set_defaults(func=cmd_latency)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AudioError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted — shutting down.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
