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


def test_native_view_commands_never_run_on_qt_thread_and_mouse_moves_coalesce() -> None:
    from snowlink.config import UserPreferences
    from snowlink.ui.pages.view import ViewPage

    _ensure_qapp()

    class Engine:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def receiver_set_visible(self, visible: bool) -> None:
            self.calls.append(("visible", visible))

        def receiver_resize(self) -> None:
            self.calls.append(("resize",))

        def decoder_status(self) -> dict[str, int]:
            self.calls.append(("decoder_status",))
            return {"decoded_width": 1920, "decoded_height": 1080}

        def send_input(self, **event) -> None:
            self.calls.append(("input", event))

    class Dispatcher:
        def __init__(self) -> None:
            self.callbacks: list = []

        def dispatch(self, callback) -> bool:
            self.callbacks.append(callback)
            return True

    page = ViewPage(UserPreferences())
    engine = Engine()
    dispatcher = Dispatcher()
    page._native_engine = engine  # noqa: SLF001
    page._session = dispatcher  # type: ignore[assignment]  # noqa: SLF001

    page.native_surface_changed(True)
    for x in range(100):
        page.native_input_event({"kind": 1, "x": x, "y": 50, "width": 960, "height": 540})

    # No DLL-facing method executes synchronously from the Qt handlers.
    assert engine.calls == []
    assert len(dispatcher.callbacks) == 2  # one surface update + one coalesced mouse update

    for callback in dispatcher.callbacks:
        callback()
    assert engine.calls[:2] == [("visible", True), ("resize",)]
    assert engine.calls[2] == ("decoder_status",)
    assert engine.calls[3][0] == "input"
    # The newest mouse event wins; x=99 maps to source x=198.
    assert engine.calls[3][1]["x"] == 198
    page.deleteLater()


def test_native_fullscreen_preserves_video_hwnd() -> None:
    from snowlink.ui.windows import ViewSessionWindow

    _ensure_qapp()
    window = ViewSessionWindow()
    window.show()
    hwnd = window.native_video_handle
    window._toggle_fullscreen()  # noqa: SLF001
    assert window.isFullScreen()
    assert window.native_video_handle == hwnd
    window._toggle_fullscreen()  # noqa: SLF001
    assert not window.isFullScreen()
    assert window.native_video_handle == hwnd
    window.close()
    window.deleteLater()


def test_native_video_surface_opts_out_of_qt_backing_store_painting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPaintEvent

    from snowlink.ui.styles import APP_STYLESHEET
    from snowlink.ui.windows import NativeVideoSurface

    app = _ensure_qapp()
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet(APP_STYLESHEET)
    surface = NativeVideoSurface()
    surface.ensurePolished()
    assert surface.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert surface.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    assert surface.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert not surface.autoFillBackground()
    assert not surface.updatesEnabled()

    # Native mode owns the HWND and accepts Qt paint events without painting a
    # QWidget/QSS background over the swap chain.
    monkeypatch.setattr(
        "snowlink.ui.windows.QPainter",
        lambda *_args: pytest.fail("native paint event constructed a Qt painter"),
    )
    event = QPaintEvent(surface.rect())
    surface.paintEvent(event)
    assert event.isAccepted()
    surface.deleteLater()
    app.setStyleSheet(previous_stylesheet)


def test_native_video_surface_switches_back_to_legacy_qpixmap_painting() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap

    from snowlink.ui.windows import NativeVideoSurface

    app = _ensure_qapp()
    surface = NativeVideoSurface()
    surface.resize(80, 60)
    pixmap = QPixmap(8, 6)
    pixmap.fill(QColor(220, 30, 40))
    surface.setPixmap(pixmap)

    assert not surface.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    assert surface.updatesEnabled()
    surface.show()
    app.processEvents()
    center = surface.grab().toImage().pixelColor(40, 30)
    assert (center.red(), center.green(), center.blue()) == (220, 30, 40)
    surface.close()
    surface.deleteLater()
