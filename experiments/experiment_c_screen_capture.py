#!/usr/bin/env python3
"""Experiment C — DXcam local screen-capture validation and benchmarking.

Phase 0 validation only. No networking, WebRTC, system audio, or product UI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.media.capture_errors import (  # noqa: E402
    CaptureError,
    format_failure_human,
)
from snowlink.media.capture_models import (  # noqa: E402
    DEFAULT_PRESET,
    MAX_DURATION_S,
    PRESETS,
    CaptureConfiguration,
    resolve_preset,
    utc_now_iso,
    validate_capture_configuration,
)
from snowlink.media.experiment_c_results import write_result  # noqa: E402
from snowlink.media.screen_capture import run_capture_session  # noqa: E402
from snowlink.platform_win.monitors import (  # noqa: E402
    MonitorEnumerationError,
    enumerate_monitors,
    format_monitor_list,
    is_windows,
)

DEFAULT_RESULTS_DIR = Path("experiment-results") / "experiment-c"


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _results_dir(args: argparse.Namespace) -> Path:
    return Path(args.results_dir)


def _config_from_args(
    args: argparse.Namespace,
    *,
    show_preview: bool,
    preset_name: str | None = None,
    fps: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration: int | None = None,
) -> CaptureConfiguration:
    return validate_capture_configuration(
        monitor=int(args.monitor),
        backend=str(args.backend),
        fps=int(fps if fps is not None else args.fps),
        width=int(width if width is not None else args.width),
        height=int(height if height is not None else args.height),
        duration=int(duration if duration is not None else args.duration),
        cursor_requested=bool(getattr(args, "show_cursor", False)),
        show_preview=show_preview,
        preset_name=preset_name,
    )


def cmd_list(args: argparse.Namespace) -> int:
    if not is_windows():
        print("Experiment C monitor listing requires Windows.", file=sys.stderr)
        return 2
    try:
        monitors = enumerate_monitors()
    except MonitorEnumerationError as exc:
        print(f"Monitor enumeration failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(
            {
                "experiment": "experiment_c_screen_capture",
                "monitor_index_policy": (
                    "Snowlink --monitor is a logical index (primary first, then "
                    "desktop origin). It is mapped to DXcam device_idx/output_idx "
                    "by desktop rectangle / HMONITOR; indices are not assumed equal."
                ),
                "monitors": [m.to_dict() for m in monitors],
            }
        )
    else:
        print(format_monitor_list(monitors), end="")
    return 0


def _emit_result(
    result: Any,
    args: argparse.Namespace,
    *,
    write_file: bool,
) -> Path | None:
    path: Path | None = None
    if write_file:
        path = write_result(result, _results_dir(args))
    if args.json:
        _print_json(result.to_dict())
    else:
        cfg = result.configuration
        status = "PASS" if result.success else "FAIL"
        print(f"Experiment C {status}")
        if cfg is not None:
            print(
                f"  monitor={cfg.monitor} backend={cfg.backend} "
                f"requested={cfg.requested_width}x{cfg.requested_height}"
                f"@{cfg.requested_fps}"
            )
        print(
            f"  capture_fps={result.capture.actual_fps:.2f} "
            f"preview_fps={result.render.actual_fps:.2f} "
            f"captured={result.capture.frames_captured} "
            f"rendered={result.render.frames_rendered} "
            f"dropped={result.capture.overwritten_frames} "
            f"null={result.capture.null_frames}"
        )
        if result.timing_ms.frame_age_average is not None:
            print(
                f"  frame_age_avg_ms={result.timing_ms.frame_age_average:.2f} "
                f"frame_age_p95_ms={result.timing_ms.frame_age_p95} "
                f"(local approximate)"
            )
        if result.resources.cpu_percent_average is not None:
            print(
                f"  cpu_avg={result.resources.cpu_percent_average:.1f}% "
                f"cpu_peak={result.resources.cpu_percent_peak} "
                f"mem_peak_mb={result.resources.memory_mb_peak}"
            )
        for err in result.errors:
            print()
            from snowlink.media.capture_errors import CaptureFailure

            failure = CaptureFailure(
                code=str(err.get("code", "UNEXPECTED_CAPTURE_ERROR")),
                message=str(err.get("message", "")),
                likely_cause=str(err.get("likely_cause", "")),
                suggested_next_step=str(err.get("suggested_next_step", "")),
                exception_type=err.get("exception_type"),
            )
            print(format_failure_human(failure))
        if path is not None:
            print(f"  result_file={path}")
    return path


def cmd_preview(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(
            args,
            show_preview=True,
            duration=int(getattr(args, "duration", MAX_DURATION_S)),
        )
    except CaptureError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2

    print(
        f"Starting preview  monitor={config.monitor} backend={config.backend} "
        f"{config.requested_width}x{config.requested_height}@{config.requested_fps}"
    )
    print("Press Esc or close the window to stop. Ctrl+C also shuts down cleanly.")
    code, result = run_capture_session(config, honor_duration=False)
    _emit_result(result, args, write_file=False)
    return code


def cmd_benchmark(args: argparse.Namespace) -> int:
    show_preview = not bool(args.no_preview)
    preset_name: str | None = None
    fps = int(args.fps)
    width = int(args.width)
    height = int(args.height)
    if args.preset:
        preset = resolve_preset(args.preset)
        preset_name = preset.name
        fps = preset.fps
        width = preset.width
        height = preset.height
    try:
        config = validate_capture_configuration(
            monitor=int(args.monitor),
            backend=str(args.backend),
            fps=fps,
            width=width,
            height=height,
            duration=int(args.duration),
            cursor_requested=bool(args.show_cursor),
            show_preview=show_preview,
            preset_name=preset_name,
        )
    except CaptureError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2

    print(
        f"Starting benchmark  monitor={config.monitor} backend={config.backend} "
        f"{config.requested_width}x{config.requested_height}@{config.requested_fps} "
        f"duration={config.duration_s}s preview={'on' if show_preview else 'off'}"
        + (f" preset={preset_name}" if preset_name else "")
    )
    code, result = run_capture_session(config, honor_duration=True)
    _emit_result(result, args, write_file=True)
    return code


def cmd_suite(args: argparse.Namespace) -> int:
    show_preview = bool(args.show_preview)
    overall = 0
    suite_started = utc_now_iso()
    summaries: list[dict[str, Any]] = []

    for preset in (PRESETS["low"], PRESETS["balanced"], PRESETS["high"]):
        print("-" * 72)
        print(
            f"Preset {preset.name}: {preset.width}x{preset.height}@{preset.fps} "
            f"for {args.duration_per_preset}s"
        )
        try:
            config = validate_capture_configuration(
                monitor=int(args.monitor),
                backend=str(args.backend),
                fps=preset.fps,
                width=preset.width,
                height=preset.height,
                duration=int(args.duration_per_preset),
                cursor_requested=bool(args.show_cursor),
                show_preview=show_preview,
                preset_name=preset.name,
            )
        except CaptureError as exc:
            print(format_failure_human(exc.failure), file=sys.stderr)
            overall = 2
            summaries.append(
                {"preset": preset.name, "success": False, "error": exc.failure.to_dict()}
            )
            continue

        code, result = run_capture_session(config, honor_duration=True)
        path = _emit_result(result, args, write_file=True)
        summaries.append(
            {
                "preset": preset.name,
                "success": result.success,
                "exit_code": code,
                "capture_fps": result.capture.actual_fps,
                "result_file": str(path) if path else None,
            }
        )
        if code != 0:
            overall = code if overall == 0 else overall
        # Do not claim High is supported merely because the run finished.
        if preset.name == "high" and result.success:
            print(
                "Note: High preset completed; inspect FPS/CPU/memory before treating "
                "it as supported on this machine."
            )

    print("-" * 72)
    print(f"Suite finished (started {suite_started})")
    if args.json:
        _print_json({"suite": summaries})
    else:
        for row in summaries:
            mark = "PASS" if row.get("success") else "FAIL"
            print(
                f"  {row['preset']:9} {mark}  "
                f"capture_fps={row.get('capture_fps')}  "
                f"file={row.get('result_file')}"
            )
    return overall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Snowlink Experiment C — local DXcam screen-capture validation "
            "(no networking)."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List monitors and DXcam backend availability")
    p_list.add_argument("--json", action="store_true", help="Print JSON")
    p_list.set_defaults(func=cmd_list)

    def add_common(p: argparse.ArgumentParser, *, with_duration: bool) -> None:
        p.add_argument("--monitor", type=int, default=0, help="Logical monitor index")
        p.add_argument(
            "--backend",
            default="dxgi",
            help="Capture backend (dxgi or winrt when available)",
        )
        p.add_argument(
            "--fps",
            type=int,
            default=DEFAULT_PRESET.fps,
            help=f"Target capture FPS (default {DEFAULT_PRESET.fps})",
        )
        p.add_argument(
            "--width",
            type=int,
            default=DEFAULT_PRESET.width,
            help=f"Output width (default {DEFAULT_PRESET.width})",
        )
        p.add_argument(
            "--height",
            type=int,
            default=DEFAULT_PRESET.height,
            help=f"Output height (default {DEFAULT_PRESET.height})",
        )
        p.add_argument(
            "--show-cursor",
            action="store_true",
            help="Request cursor capture (WinRT only in DXcam)",
        )
        p.add_argument("--json", action="store_true", help="Print result JSON to stdout")
        p.add_argument(
            "--results-dir",
            default=str(DEFAULT_RESULTS_DIR),
            help="Directory for benchmark JSON results",
        )
        if with_duration:
            p.add_argument(
                "--duration",
                type=int,
                default=60,
                help="Benchmark duration in seconds (default 60)",
            )

    p_preview = sub.add_parser("preview", help="Live local preview with stats overlay")
    add_common(p_preview, with_duration=False)
    p_preview.add_argument(
        "--duration",
        type=int,
        default=MAX_DURATION_S,
        help="Safety time limit in seconds (default: max); Esc stops earlier",
    )
    p_preview.set_defaults(func=cmd_preview)

    p_bench = sub.add_parser("benchmark", help="Timed capture benchmark")
    add_common(p_bench, with_duration=True)
    p_bench.add_argument(
        "--no-preview",
        action="store_true",
        help="Do not open a preview window (still scales frames for metrics)",
    )
    p_bench.add_argument(
        "--preset",
        choices=sorted(PRESETS.keys()),
        help="Apply a named quality preset (overrides width/height/fps)",
    )
    p_bench.set_defaults(func=cmd_benchmark)

    p_suite = sub.add_parser(
        "suite",
        help="Run Low, Balanced, and High presets sequentially (no preview by default)",
    )
    p_suite.add_argument("--monitor", type=int, default=0)
    p_suite.add_argument("--backend", default="dxgi")
    p_suite.add_argument(
        "--duration-per-preset",
        type=int,
        default=60,
        help="Seconds per preset (default 60)",
    )
    p_suite.add_argument(
        "--show-preview",
        action="store_true",
        help="Show preview windows during the suite (off by default)",
    )
    p_suite.add_argument("--show-cursor", action="store_true")
    p_suite.add_argument("--json", action="store_true")
    p_suite.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
    )
    p_suite.set_defaults(func=cmd_suite)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CaptureError as exc:
        print(format_failure_human(exc.failure), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
