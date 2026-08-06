#!/usr/bin/env python3
"""Frozen / source entry for the Snowlink PySide6 GUI.

Usage (dev)::

    python packaging/snowlink_gui_entry.py

Usage (frozen)::

    Snowlink.exe
    Snowlink.exe --experiment experiment_c_screen_capture list

``--experiment`` runs a Phase 0 script ``main(argv)`` without opening the GUI
(used by Diagnostics when the app is frozen).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def _ensure_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        exe_dir = Path(sys.executable).resolve().parent
        for path in (
            meipass / "experiments",
            exe_dir / "experiments",
            exe_dir / "_internal" / "experiments",
            meipass,
            exe_dir,
        ):
            if path.is_dir() and str(path) not in sys.path:
                # experiments/ parent must be on path for `import experiment_*`
                target = path if path.name != "experiments" else path.parent
                if str(target) not in sys.path:
                    sys.path.insert(0, str(target))
                if path.name == "experiments" and str(path) not in sys.path:
                    sys.path.insert(0, str(path))
        return
    src = root / "src"
    experiments = root / "experiments"
    for path in (src, experiments):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _run_experiment(script_stem: str, argv: Sequence[str]) -> int:
    """Import ``experiments/<stem>.py`` and call ``main(argv)``."""
    stem = Path(script_stem).stem
    # Prefer import when the module is on sys.path (dev + frozen hiddenimports).
    module_name = stem
    try:
        module = __import__(module_name)
    except ImportError:
        from snowlink.ui.paths import experiment_script

        script = experiment_script(stem)
        if not script.is_file():
            print(f"Experiment script not found: {stem}", file=sys.stderr)
            return 2
        import runpy

        # run_path executes as __main__; set argv first.
        sys.argv = [str(script), *list(argv)]
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            if isinstance(code, int):
                return code
            return 1
        return 0

    main = getattr(module, "main", None)
    if main is None:
        print(f"Experiment module {module_name!r} has no main()", file=sys.stderr)
        return 2
    return int(main(list(argv)))


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_paths()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--experiment":
        if len(args) < 2:
            print(
                "Usage: Snowlink.exe --experiment <script_stem> [args...]",
                file=sys.stderr,
            )
            return 2
        return _run_experiment(args[1], args[2:])

    try:
        from snowlink.ui.app import run_app
    except ImportError as exc:
        print(
            "Snowlink GUI requires PySide6.\n"
            'Install with: pip install -e ".[ui]"\n'
            f"Import error: {exc}",
            file=sys.stderr,
        )
        return 2
    return int(run_app())


if __name__ == "__main__":
    raise SystemExit(main())
