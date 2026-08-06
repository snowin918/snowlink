#!/usr/bin/env python3
"""Frozen-friendly Phase 0 launcher for Experiments A and B.

Usage (dev)::

    python experiments/phase0_launcher.py a list
    python experiments/phase0_launcher.py b guide

Usage (built exe)::

    snowlink-phase0.exe a list
    snowlink-phase0.exe b serve --ip 192.168.1.25 --port 3847 --session-name vpn-off-off
    snowlink-phase0.exe b connect --ip 192.168.1.25 --session-name vpn-off-off --source-ip 192.168.1.30
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def _ensure_src_on_path() -> None:
    if getattr(sys, "frozen", False):
        return
    src = Path(__file__).resolve().parents[1] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_src_on_path()
    parser = argparse.ArgumentParser(
        prog="snowlink-phase0",
        description="Snowlink Phase 0 experiments (A adapter bind, B two-machine TCP)",
    )
    sub = parser.add_subparsers(dest="experiment", required=True)

    sub.add_parser("a", help="Experiment A — adapter list / serve / connect").add_argument(
        "a_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to Experiment A",
    )
    sub.add_parser("b", help="Experiment B — guide / serve / connect / summarize").add_argument(
        "b_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to Experiment B",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    # argparse.REMAINDER keeps a leading "--" if users write: a -- list
    def _strip(rest: list[str]) -> list[str]:
        if rest and rest[0] == "--":
            return rest[1:]
        return rest

    if args.experiment == "a":
        from experiment_a_adapter_bind import main as a_main

        return int(a_main(_strip(list(args.a_args))))
    if args.experiment == "b":
        from experiment_b_two_machine_tcp import main as b_main

        return int(b_main(_strip(list(args.b_args))))
    parser.error(f"Unknown experiment: {args.experiment}")
    return 2


if __name__ == "__main__":
    # Allow importing sibling experiment modules when run from source or frozen.
    exp_dir = Path(__file__).resolve().parent
    if str(exp_dir) not in sys.path:
        sys.path.insert(0, str(exp_dir))
    raise SystemExit(main())
