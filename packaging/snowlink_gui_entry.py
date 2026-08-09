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


def _selftest_share() -> int:
    """Exercise GUI-like share startup (Qt + asyncio worker + DXcam)."""
    import asyncio
    import traceback

    from PySide6.QtWidgets import QApplication

    from snowlink.net.adapter_selection import (
        annotate_adapters,
        select_preferred_endpoint,
    )
    from snowlink.platform_win.adapters import enumerate_adapters, is_windows
    from snowlink.rtc.screen_session import ScreenShareConfiguration, run_screen_share

    app = QApplication.instance() or QApplication([])
    if not is_windows():
        print("selftest-share: Windows required", file=sys.stderr)
        return 2
    adapters = annotate_adapters(enumerate_adapters())
    selected = select_preferred_endpoint(adapters)
    bind_ip = str(selected.ipv4) if selected is not None else "127.0.0.1"
    print(f"selftest-share: bind_ip={bind_ip}")

    async def _run() -> int:
        stop = asyncio.Event()

        async def _stop_later() -> None:
            await asyncio.sleep(3.0)
            stop.set()

        asyncio.create_task(_stop_later())
        config = ScreenShareConfiguration.from_preset(
            bind_ip=bind_ip,
            signaling_port=19877,
            monitor=0,
            backend="dxgi",
            preset="low",
            enable_audio=False,
            auto_approve=True,
        )
        try:
            state = await run_screen_share(config, stop_event=stop)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            print(f"selftest-share: raised {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(
            f"selftest-share: phase={state.phase!r} error={state.error!r} "
            f"detail={state.detail!r}"
        )
        return 0 if state.phase in {"stopped", "stopping", "waiting_for_viewer"} or (
            state.phase == "failed" and False
        ) else (0 if state.error is None else 1)

    # Match GUI: run share on a dedicated asyncio thread.
    import threading

    result: list[int] = [2]

    def _thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result[0] = int(loop.run_until_complete(_run()))
        finally:
            loop.close()

    t = threading.Thread(target=_thread, name="selftest-share", daemon=True)
    t.start()
    # Process Qt events while the worker runs (closer to real GUI).
    while t.is_alive():
        app.processEvents()
        t.join(0.05)
    _ = app
    return int(result[0])


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
    if args and args[0] == "--selftest-share":
        return _selftest_share()

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
