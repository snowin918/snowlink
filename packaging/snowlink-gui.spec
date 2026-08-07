# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the Snowlink windowed GUI app.

Produces::

    packaging/dist/Snowlink/Snowlink.exe

This is separate from ``snowlink-phase0.exe`` (console A+B only).
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPEC).resolve().parent  # type: ignore[name-defined]
ROOT = SPECDIR.parent
SRC = ROOT / "src"
EXPERIMENTS = ROOT / "experiments"
ENTRY = SPECDIR / "snowlink_gui_entry.py"

# PySide6 (and optional media stacks if installed in the build venv)
datas: list = [(str(EXPERIMENTS), "experiments")]
binaries: list = []
hiddenimports: list = [
    "snowlink",
    "snowlink.ui",
    "snowlink.ui.app",
    "snowlink.ui.main_window",
    "snowlink.ui.workers",
    "snowlink.ui.paths",
    "snowlink.ui.argv_builders",
    "snowlink.ui.styles",
    "snowlink.ui.pages",
    "snowlink.ui.pages.home",
    "snowlink.ui.pages.share",
    "snowlink.ui.pages.view",
    "snowlink.ui.pages.diagnostics",
    "experiment_a_adapter_bind",
    "experiment_b_two_machine_tcp",
    "experiment_c_screen_capture",
    "experiment_d_audio_loopback",
    "experiment_e_webrtc_video",
    "experiment_f_webrtc_audio",
]
hiddenimports += collect_submodules("snowlink")

# Include media/audio stacks when present in the build venv. PyAudioWPatch
# must be collect_all'd — analysis alone may pull only _portaudiowpatch.pyd
# and omit the importable ``pyaudiowpatch`` package (breaks system-audio share).
for pkg in (
    "PySide6",
    "shiboken6",
    "dxcam",
    "cv2",
    "av",
    "aiortc",
    "aiohttp",
    "pyaudiowpatch",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        # Optional dependency not installed in the build environment.
        pass
hiddenimports += [
    "pyaudiowpatch",
    "pyaudiowpatch.__main__",
    "_portaudiowpatch",
    "numpy",
]

a = Analysis(  # noqa: F821  # type: ignore[name-defined]
    [str(ENTRY)],
    pathex=[str(SRC), str(EXPERIMENTS), str(ROOT), str(SPECDIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "mypy",
        "ruff",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821  # type: ignore[name-defined]

exe = EXE(  # noqa: F821  # type: ignore[name-defined]
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Snowlink",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821  # type: ignore[name-defined]
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Snowlink",
)
