#!/usr/bin/env python3
"""Sample process CPU/RSS (and optional stats JSONL) for MVP soak runs.

Usage examples (PowerShell)::

    # Sample this Python process for 60s every 5s (smoke)
    python scripts/dev/soak_sample.py --duration-s 60 --interval-s 5

    # Attach to a running Snowlink.exe PID during a Share/View soak
    python scripts/dev/soak_sample.py --pid 12345 --duration-s 1800 --out soak-30m.jsonl

Record start/end RSS and peak; pass criteria in docs/runbooks/mvp-acceptance.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _sample_process(pid: int | None) -> dict[str, float | int | None]:
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit(
            "psutil is required for soak sampling (pip install psutil)."
        ) from exc

    proc = psutil.Process(pid) if pid is not None else psutil.Process()
    # Prime cpu_percent baseline on first call.
    proc.cpu_percent(interval=None)
    time.sleep(0.05)
    cpu = float(proc.cpu_percent(interval=None))
    mem = proc.memory_info()
    rss_mb = float(mem.rss) / (1024.0 * 1024.0)
    return {
        "pid": int(proc.pid),
        "cpu_percent": cpu,
        "rss_mb": rss_mb,
        "ts": time.time(),
        "mono_s": time.monotonic(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=None, help="Target PID (default: self)")
    parser.add_argument(
        "--duration-s",
        type=float,
        default=60.0,
        help="Total sampling duration in seconds",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=10.0,
        help="Seconds between samples",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSONL output path",
    )
    parser.add_argument(
        "--av-skew-ms",
        type=float,
        default=None,
        help="Optional fixed av_skew_ms to record each sample (manual annotation)",
    )
    args = parser.parse_args(argv)

    duration = max(1.0, float(args.duration_s))
    interval = max(0.5, float(args.interval_s))
    out_path: Path | None = args.out
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    samples: list[dict[str, float | int | None]] = []
    print(
        f"soak_sample: pid={args.pid or 'self'} duration={duration}s interval={interval}s",
        flush=True,
    )

    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        psutil = None  # type: ignore[assignment]

    while True:
        try:
            row = _sample_process(args.pid)
        except Exception as exc:
            # Target process may exit when share --duration ends; keep samples.
            if psutil is not None and isinstance(exc, psutil.Error):
                print(f"# target process ended: {exc}", flush=True)
                break
            raise
        if args.av_skew_ms is not None:
            row["av_skew_ms"] = float(args.av_skew_ms)
        samples.append(row)
        line = json.dumps(row, separators=(",", ":"))
        print(line, flush=True)
        if out_path is not None:
            with out_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

        elapsed = time.monotonic() - started
        if elapsed >= duration:
            break
        time.sleep(min(interval, max(0.0, duration - elapsed)))

    if not samples:
        print("# summary no samples collected", flush=True)
        return 1

    rss_values = [float(s["rss_mb"]) for s in samples if s.get("rss_mb") is not None]
    cpu_values = [
        float(s["cpu_percent"]) for s in samples if s.get("cpu_percent") is not None
    ]
    summary = {
        "samples": len(samples),
        "rss_mb_start": rss_values[0] if rss_values else None,
        "rss_mb_end": rss_values[-1] if rss_values else None,
        "rss_mb_peak": max(rss_values) if rss_values else None,
        "rss_mb_growth": (
            (rss_values[-1] - rss_values[0]) if len(rss_values) >= 2 else None
        ),
        "cpu_percent_avg": (sum(cpu_values) / len(cpu_values)) if cpu_values else None,
        "cpu_percent_peak": max(cpu_values) if cpu_values else None,
        "duration_s": time.monotonic() - started,
    }
    print("# summary " + json.dumps(summary, separators=(",", ":")), flush=True)
    if out_path is not None:
        summary_path = out_path.with_suffix(out_path.suffix + ".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"# wrote {out_path} and {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
