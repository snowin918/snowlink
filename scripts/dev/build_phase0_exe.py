#!/usr/bin/env python3
"""Build packaging/dist/snowlink-phase0.exe (Experiments A + B console only)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "snowlink-phase0.spec"
DIST = REPO_ROOT / "packaging" / "dist"
WORK = REPO_ROOT / "packaging" / "build"


def main() -> int:
    if not SPEC.is_file():
        print(f"Missing spec: {SPEC}", file=sys.stderr)
        return 2

    print(f"Repository: {REPO_ROOT}")
    print(f"Python: {sys.executable}")
    print('Ensuring PyInstaller (pip install -e ".[dev]")...')
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-e", ".[dev]"],
        cwd=REPO_ROOT,
    )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        str(SPEC),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=REPO_ROOT)

    exe = DIST / "snowlink-phase0.exe"
    if not exe.is_file():
        print(f"Build finished but exe not found: {exe}", file=sys.stderr)
        return 2

    print()
    print(f"Built: {exe}")
    print("This exe is console-only for Experiments A and B.")
    print("Product GUI is not packaged — use: python -m snowlink")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
