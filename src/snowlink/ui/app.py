"""QApplication bootstrap for the Snowlink shell."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from snowlink.logging_setup import setup_logging
from snowlink.platform_win.paths import ensure_app_dirs, logs_dir
from snowlink.shutdown import run_app_shutdown
from snowlink.ui.main_window import MainWindow
from snowlink.ui.paths import logo_ico
from snowlink.ui.styles import APP_STYLESHEET


def _app_icon() -> QIcon:
    path = logo_ico()
    if path is None:
        return QIcon()
    return QIcon(str(path))


def _redirect_frozen_stdio() -> None:
    """Keep windowed PyInstaller builds from dying on print()/stdio writes."""
    if not getattr(sys, "frozen", False):
        return
    try:
        ensure_app_dirs()
        log_path = logs_dir() / "console.log"
        handle = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
        if sys.stdout is None or not hasattr(sys.stdout, "write"):
            sys.stdout = handle  # type: ignore[assignment]
        if sys.stderr is None or not hasattr(sys.stderr, "write"):
            sys.stderr = handle  # type: ignore[assignment]
    except Exception:
        try:
            devnull = open(Path("NUL" if sys.platform == "win32" else "/dev/null"), "w")  # noqa: SIM115
            if sys.stdout is None:
                sys.stdout = devnull  # type: ignore[assignment]
            if sys.stderr is None:
                sys.stderr = devnull  # type: ignore[assignment]
        except Exception:
            pass


def _install_exception_hooks(app: QApplication) -> None:
    """Surface uncaught errors instead of silently exiting a windowed exe."""

    def _show(title: str, text: str) -> None:
        try:
            QMessageBox.critical(None, title, text[:4000])
        except Exception:
            pass

    def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]
            return
        detail = "".join(traceback.format_exception(exc_type, exc, tb))  # type: ignore[arg-type]
        _show("Snowlink error", f"{exc_type.__name__}: {exc}\n\n{detail}")

    sys.excepthook = _excepthook

    if hasattr(sys, "unraisablehook"):

        def _unraisable(unraisable: object) -> None:
            exc = getattr(unraisable, "exc_value", None)
            if exc is None:
                return
            _show("Snowlink error", f"Background error: {exc}")

        sys.unraisablehook = _unraisable  # type: ignore[assignment]

    _ = app  # app kept for future thread hooks


def _check_vcredist_hint() -> None:
    """Show a soft hint when common native deps fail to import (missing VC++)."""
    try:
        import av  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(
            None,
            "Missing runtime?",
            "PyAV failed to import. On a clean Windows PC this often means the "
            "Microsoft Visual C++ Redistributable is missing.\n\n"
            f"Detail: {exc}\n\n"
            "Install the latest VC++ x64 redistributable, then relaunch Snowlink.",
        )


def run_app(argv: list[str] | None = None) -> int:
    """Create the Qt application and show the main window."""
    _redirect_frozen_stdio()
    ensure_app_dirs()
    setup_logging()
    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(args)
    assert isinstance(app, QApplication)
    app.setApplicationName("Snowlink")
    app.setOrganizationName("Snowlink")
    app.setStyleSheet(APP_STYLESHEET)
    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    _install_exception_hooks(app)

    def _on_about_to_quit() -> None:
        run_app_shutdown()

    app.aboutToQuit.connect(_on_about_to_quit)

    _check_vcredist_hint()

    window = MainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
