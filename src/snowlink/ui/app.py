"""QApplication bootstrap for the Snowlink shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from snowlink.logging_setup import setup_logging
from snowlink.platform_win.paths import ensure_app_dirs
from snowlink.shutdown import register_app_shutdown, run_app_shutdown
from snowlink.ui.main_window import MainWindow
from snowlink.ui.styles import APP_STYLESHEET


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

    def _on_about_to_quit() -> None:
        run_app_shutdown()

    app.aboutToQuit.connect(_on_about_to_quit)
    register_app_shutdown("noop", lambda: None)

    _check_vcredist_hint()

    window = MainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
