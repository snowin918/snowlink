#!/usr/bin/env python3
"""Validate archived Phase 0 experiment evidence (remediation helper).

Does not run network tests or capture hardware, and does not rewrite go/no-go
decisions.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.media.experiment_c_results import (  # noqa: E402
    evidence_exit_code as evidence_exit_code_c,
)
from snowlink.media.experiment_c_results import (  # noqa: E402
    format_experiment_c_evidence_report,
    validate_experiment_c_machines,
)
from snowlink.net.experiment_b_results import (  # noqa: E402
    evidence_exit_code as evidence_exit_code_b,
)
from snowlink.net.experiment_b_results import (  # noqa: E402
    format_evidence_report,
    validate_experiment_b_matrix,
)

DEFAULT_B_RESULTS = _REPO_ROOT / "experiment-results" / "experiment-b"
DEFAULT_C_RESULTS = _REPO_ROOT / "experiment-results" / "experiment-c"


def cmd_experiment_b(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir)
    rows = validate_experiment_b_matrix(results_dir)
    print(format_evidence_report(rows))
    print()
    print(f"Results directory: {results_dir}")
    if not results_dir.is_dir():
        print(
            "Note: directory does not exist yet - run Experiment B connect "
            "commands first.",
            file=sys.stderr,
        )
    return evidence_exit_code_b(rows)


def cmd_experiment_c(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir)
    rows = validate_experiment_c_machines(results_dir)
    print(format_experiment_c_evidence_report(rows))
    print()
    print(f"Results directory: {results_dir}")
    if not results_dir.is_dir():
        print(
            "Note: directory does not exist yet - run Experiment C Balanced "
            "benchmarks with --machine-label first.",
            file=sys.stderr,
        )
    return evidence_exit_code_c(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Phase 0 archived evidence for remediation gates",
    )
    parser.add_argument(
        "--experiment",
        required=True,
        choices=("b", "c"),
        help="Which experiment matrix to validate (b or c)",
    )
    parser.add_argument(
        "--results-dir",
        default=None,
        help=(
            "JSON results directory (default: experiment-results/experiment-b "
            "or experiment-results/experiment-c)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.experiment == "b":
        if args.results_dir is None:
            args.results_dir = str(DEFAULT_B_RESULTS)
        return cmd_experiment_b(args)
    if args.experiment == "c":
        if args.results_dir is None:
            args.results_dir = str(DEFAULT_C_RESULTS)
        return cmd_experiment_c(args)
    parser.error(f"Unsupported experiment: {args.experiment}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
