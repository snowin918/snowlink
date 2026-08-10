"""Locate and load ``snowlink_engine.dll`` via ctypes."""

from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from pathlib import Path


DLL_NAME = "snowlink_engine.dll"


def candidate_dll_paths() -> list[Path]:
    """Return ordered search paths for the native engine DLL."""
    env = os.environ.get("SNOWLINK_ENGINE_DLL")
    paths: list[Path] = []
    if env:
        paths.append(Path(env))

    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # .../src/snowlink/native_engine -> repo
    native_root = repo_root / "native"

    paths.extend(
        [
            # CMake multi-config (Visual Studio)
            native_root / "build" / "bin" / "Release" / DLL_NAME,
            native_root / "build" / "bin" / "Debug" / DLL_NAME,
            native_root / "build" / "bin" / "RelWithDebInfo" / DLL_NAME,
            # Single-config generators
            native_root / "build" / "bin" / DLL_NAME,
            # Next to frozen executable
            Path(sys.executable).resolve().parent / DLL_NAME,
            # PyInstaller onedir stores collected binaries in _internal
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / DLL_NAME,
            # Optional sidecar beside the Python package
            here.parent / DLL_NAME,
        ]
    )

    # De-dupe while preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def find_engine_dll() -> Path | None:
    for path in candidate_dll_paths():
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def load_engine_dll() -> ctypes.CDLL:
    """Load the engine DLL or raise FileNotFoundError / OSError."""
    path = find_engine_dll()
    if path is None:
        searched = ", ".join(str(p) for p in candidate_dll_paths()[:6])
        raise FileNotFoundError(
            f"{DLL_NAME} not found. Build native/ with CMake, or set "
            f"SNOWLINK_ENGINE_DLL. Searched: {searched}, ..."
        )
    return ctypes.WinDLL(str(path))


def clear_loader_cache() -> None:
    load_engine_dll.cache_clear()
