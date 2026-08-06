"""QApplication bootstrap for the Snowlink shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from snowlink.ui.main_window import MainWindow
from snowlink.ui.styles import APP_STYLESHEET


def run_app(argv: list[str] | None = None) -> int:
    """Create the Qt application and show the main window."""
    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(args)
    assert isinstance(app, QApplication)
    app.setApplicationName("Snowlink")
    app.setOrganizationName("Snowlink")
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
