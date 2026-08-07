"""Main window with stacked Home / Share / View / Diagnostics / Settings pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snowlink import __version__
from snowlink.config import UserPreferences, load_preferences, save_preferences
from snowlink.diagnostics.workflow import LiveSessionSnapshot
from snowlink.shutdown import run_app_shutdown
from snowlink.ui.pages.diagnostics import DiagnosticsPage
from snowlink.ui.pages.home import HomePage
from snowlink.ui.pages.settings import SettingsPage
from snowlink.ui.pages.share import SharePage
from snowlink.ui.pages.view import ViewPage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._prefs = load_preferences()
        self.setWindowTitle(f"Snowlink {__version__}")
        w = max(640, int(self._prefs.window_width))
        h = max(480, int(self._prefs.window_height))
        self.resize(w, h)
        if self._prefs.window_x is not None and self._prefs.window_y is not None:
            self.move(int(self._prefs.window_x), int(self._prefs.window_y))

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QWidget()
        nav.setFixedWidth(200)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(8)

        brand = QLabel("Snowlink")
        brand.setObjectName("brandTitle")
        brand.setStyleSheet("font-size: 20px; font-weight: 700;")
        nav_layout.addWidget(brand)
        sub = QLabel("LAN share")
        sub.setObjectName("brandSubtitle")
        nav_layout.addWidget(sub)
        nav_layout.addSpacing(12)

        self._stack = QStackedWidget()
        self._home = HomePage()
        self._share = SharePage(self._prefs)
        self._view = ViewPage(self._prefs)
        self._diagnostics = DiagnosticsPage()
        self._settings = SettingsPage()
        self._stack.addWidget(self._home)
        self._stack.addWidget(self._share)
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._diagnostics)
        self._stack.addWidget(self._settings)

        self._nav_buttons: list[QPushButton] = []
        for index, label in enumerate(
            ("Home", "Share", "View", "Diagnostics", "Settings")
        ):
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=index: self._goto(i))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)
        nav_layout.addStretch(1)

        layout.addWidget(nav)
        layout.addWidget(self._stack, 1)

        self._home.navigate.connect(self._goto_name)
        self._settings.preferences_changed.connect(self._on_prefs_changed)
        self._share._session.state_changed.connect(self._on_live_state)  # noqa: SLF001
        self._view._session.state_changed.connect(self._on_live_state)  # noqa: SLF001
        self.statusBar().showMessage(
            "MVP — WebSocket pairing + screen/audio share. Diagnostics checklist available."
        )
        self._goto(0)

    def _on_live_state(self, state: object) -> None:
        snap = LiveSessionSnapshot(
            ice_state=getattr(state, "ice_state", None),
            frames=int(getattr(state, "frames", 0) or 0),
            audio_frames=int(getattr(state, "audio_frames", 0) or 0),
            phase=getattr(state, "phase", None),
        )
        self._diagnostics.set_live_session_snapshot(snap)

    def _on_prefs_changed(self, prefs: UserPreferences) -> None:
        self._prefs = prefs
        self._share.apply_preferences(prefs)
        self._view.apply_preferences(prefs)

    def _goto(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _goto_name(self, name: str) -> None:
        mapping = {
            "home": 0,
            "share": 1,
            "view": 2,
            "diagnostics": 3,
            "settings": 4,
        }
        self._goto(mapping.get(name.lower(), 0))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt API
        try:
            self._share._session.stop()  # noqa: SLF001
            self._view._session.stop()  # noqa: SLF001
        except Exception:
            pass
        geo = self.geometry()
        self._prefs.window_x = int(geo.x())
        self._prefs.window_y = int(geo.y())
        self._prefs.window_width = int(geo.width())
        self._prefs.window_height = int(geo.height())
        # Keep last remote IP from the view form when possible.
        try:
            remote = self._view._ip.text().strip()  # noqa: SLF001 — persist UX
            if remote:
                self._prefs.last_remote_ip = remote
            source = self._view._source_ip.text().strip()  # noqa: SLF001
            if source:
                self._prefs.last_source_ip = source
            bind = self._share._selected_bind_ip()  # noqa: SLF001
            if bind:
                self._prefs.preferred_bind_ip = bind
            self._prefs.signaling_port = int(self._share._port.value())  # noqa: SLF001
            self._prefs.preset = self._share._preset.currentText()  # noqa: SLF001
            self._prefs.backend = self._share._backend.currentText()  # noqa: SLF001
            self._prefs.enable_audio = self._share._enable_audio.isChecked()  # noqa: SLF001
            mon = self._share._monitor.currentData()  # noqa: SLF001
            if mon is not None:
                self._prefs.share_monitor = int(mon)
        except Exception:
            pass
        try:
            save_preferences(self._prefs)
        except Exception:
            pass
        run_app_shutdown()
        super().closeEvent(event)
