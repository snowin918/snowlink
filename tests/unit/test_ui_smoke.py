"""Optional smoke imports for the PySide6 UI package."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def _ensure_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_import_ui_modules() -> None:
    from snowlink.ui import argv_builders, paths
    from snowlink.ui.app import run_app
    from snowlink.ui.main_window import MainWindow
    from snowlink.ui.pages import home, settings, view
    from snowlink.ui.share_controller import ShareController

    assert callable(run_app)
    assert MainWindow is not None
    assert home.HomePage is not None
    assert view.ViewPage is not None
    assert settings.SettingsPage is not None
    assert ShareController is not None
    assert paths.repo_root().name  # non-empty
    assert "a" in argv_builders.SCRIPT_NAMES


def test_home_shows_history_and_share_controls() -> None:
    from PySide6.QtWidgets import QPushButton

    from snowlink.ui.pages.home import HomePage

    _ensure_qapp()
    page = HomePage()
    labels = {b.text() for b in page.findChildren(QPushButton)}
    assert "Start Sharing" in labels
    assert "View Another Computer" in labels
    assert "Share This Computer" not in labels
    assert page._history.count() >= 1  # noqa: SLF001
    page.deleteLater()


def test_nav_is_home_view_settings_only() -> None:
    from snowlink.ui.main_window import MainWindow

    _ensure_qapp()
    # Avoid auto-start side effects during construction beyond timer.
    win = MainWindow()
    labels = [b.text() for b in win._nav_buttons]  # noqa: SLF001
    assert labels == ["Home", "View", "Settings"]
    assert win._stack.count() == 3  # noqa: SLF001
    win.close()
    win.deleteLater()


def test_settings_hold_share_options() -> None:
    from snowlink.ui.pages.settings import SettingsPage

    _ensure_qapp()
    settings = SettingsPage()
    assert settings._auto_start.isChecked()  # noqa: SLF001
    assert settings._adapter.count() >= 0  # noqa: SLF001
    settings.deleteLater()


def test_logo_assets_resolve_and_stylesheet_is_light() -> None:
    from PySide6.QtGui import QIcon

    from snowlink.config import UserPreferences
    from snowlink.ui.main_window import _resolve_window_size
    from snowlink.ui.paths import logo_ico, logo_png
    from snowlink.ui.styles import APP_STYLESHEET

    png = logo_png()
    ico = logo_ico()
    assert png is not None and png.is_file()
    assert ico is not None and ico.is_file()
    assert not QIcon(str(ico)).isNull()
    assert "#2196F3" in APP_STYLESHEET
    assert "#F7FBFF" in APP_STYLESHEET
    assert "#212121" in APP_STYLESHEET
    prefs = UserPreferences()
    assert prefs.window_width == 700
    assert prefs.window_height == 500
    assert prefs.auto_start_share is True
    assert _resolve_window_size(UserPreferences(window_width=1040, window_height=720)) == (
        700,
        500,
    )


def test_incoming_connection_dialog_and_session_windows() -> None:
    from snowlink.security.pairing import PairingRequestInfo
    from snowlink.ui.dialogs import prompt_incoming_connection
    from snowlink.ui.windows import ShareSessionWindow, ViewSessionWindow

    _ensure_qapp()
    share_win = ShareSessionWindow()
    view_win = ViewSessionWindow()
    assert share_win.windowTitle().startswith("Snowlink")
    assert view_win.windowTitle().startswith("Snowlink")
    info = PairingRequestInfo(
        remote_addr="192.168.1.50:12345",
        code_matched=True,
        session_id="test",
    )
    assert info.remote_addr.startswith("192.168")
    assert callable(prompt_incoming_connection)
    share_win.deleteLater()
    view_win.deleteLater()
