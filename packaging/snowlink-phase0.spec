# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Snowlink Phase 0 (Experiments A + B) portable exe."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPECDIR = Path(SPEC).resolve().parent  # type: ignore[name-defined]
ROOT = SPECDIR.parent
SRC = ROOT / "src"
EXPERIMENTS = ROOT / "experiments"

hiddenimports = [
    "snowlink",
    "snowlink.net",
    "snowlink.net.adapter_models",
    "snowlink.net.adapter_selection",
    "snowlink.net.tcp_echo",
    "snowlink.net.tcp_diagnostics",
    "snowlink.net.socket_errors",
    "snowlink.net.experiment_b_models",
    "snowlink.net.experiment_b_results",
    "snowlink.platform_win",
    "snowlink.platform_win.adapters",
    "experiment_a_adapter_bind",
    "experiment_b_two_machine_tcp",
]
hiddenimports += collect_submodules("snowlink")

a = Analysis(
    [str(EXPERIMENTS / "phase0_launcher.py")],
    pathex=[str(SRC), str(EXPERIMENTS), str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "mypy",
        "ruff",
        "PySide6",
        "aiortc",
        "av",
        "dxcam",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="snowlink-phase0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
