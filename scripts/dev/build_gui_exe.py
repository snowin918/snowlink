#!/usr/bin/env python3
"""Build packaging/dist/Snowlink/Snowlink.exe (windowed GUI onedir)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "snowlink-gui.spec"
DIST = REPO_ROOT / "packaging" / "dist"
WORK = REPO_ROOT / "packaging" / "build"


def main() -> int:
    if not SPEC.is_file():
        print(f"Missing spec: {SPEC}", file=sys.stderr)
        return 2

    print(f"Repository: {REPO_ROOT}")
    print(f"Python: {sys.executable}")
    print('Ensuring GUI + packaging deps (pip install -e ".[dev,ui]")...')
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-e", ".[dev,ui]"],
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

    exe = DIST / "Snowlink" / "Snowlink.exe"
    if not exe.is_file():
        print(f"Build finished but exe not found: {exe}", file=sys.stderr)
        return 2

    print()
    print(f"Built GUI app folder: {DIST / 'Snowlink'}")
    print(f"Launch: {exe}")
    print("Distribute the whole Snowlink/ folder (onedir), not only the exe.")
    print("LAN Share/View streaming is still Phase 1 (not ready).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
