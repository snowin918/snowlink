"""Main window with Home / View / Settings (share runs in the background)."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snowlink import __version__
from snowlink.config import UserPreferences, load_preferences, save_preferences
from snowlink.session_history import (
    SessionHistoryEntry,
    prepend_history,
    utc_now_iso,
)
from snowlink.shutdown import register_app_shutdown, run_app_shutdown
from snowlink.ui.dialogs import prompt_incoming_connection
from snowlink.ui.pages.home import HomePage
from snowlink.ui.pages.settings import SettingsPage
from snowlink.ui.pages.view import ViewPage
from snowlink.ui.paths import logo_ico, logo_png
from snowlink.ui.share_controller import ShareController
from snowlink.ui.windows import ShareSessionWindow, ViewSessionWindow

_DEFAULT_W = 700
_DEFAULT_H = 500
_MIN_W = 700
_MIN_H = 500
_LEGACY_SIZES = frozenset(
    {
        (1040, 720),
        (780, 560),
        (1200, 800),
        (480, 360),
        (600, 400),
    }
)


def _resolve_window_size(prefs: UserPreferences) -> tuple[int, int]:
    """Return 700×500 default; migrate once from prior built-in defaults."""
    w = int(prefs.window_width)
    h = int(prefs.window_height)
    if (w, h) in _LEGACY_SIZES:
        return _DEFAULT_W, _DEFAULT_H
    return max(_MIN_W, w), max(_MIN_H, h)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._prefs = load_preferences()
        self._share_session_window: ShareSessionWindow | None = None
        self._view_session_window: ViewSessionWindow | None = None
        self._approval_open = False
        self._pending_share_peer: str | None = None
        self._active_share_history: SessionHistoryEntry | None = None
        self._active_view_history: SessionHistoryEntry | None = None
        self.setWindowTitle(f"Snowlink {__version__}")
        self.setMinimumSize(_MIN_W, _MIN_H)
        w, h = _resolve_window_size(self._prefs)
        self._prefs.window_width = w
        self._prefs.window_height = h
        self.resize(w, h)
        if self._prefs.window_x is not None and self._prefs.window_y is not None:
            self.move(int(self._prefs.window_x), int(self._prefs.window_y))

        icon_path = logo_ico()
        if icon_path is not None:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                self.setWindowIcon(icon)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QWidget()
        nav.setObjectName("navRail")
        nav.setFixedWidth(120)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(8, 10, 8, 10)
        nav_layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(6)
        logo_label = QLabel()
        logo_label.setObjectName("navLogo")
        png = logo_png()
        if png is not None:
            pix = QPixmap(str(png))
            if not pix.isNull():
                logo_label.setPixmap(
                    pix.scaled(
                        22,
                        22,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        brand_row.addWidget(logo_label)
        brand = QLabel("Snowlink")
        brand.setObjectName("brandWordmark")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        nav_layout.addLayout(brand_row)
        sub = QLabel("LAN share")
        sub.setObjectName("brandSubtitle")
        nav_layout.addWidget(sub)
        nav_layout.addSpacing(10)

        self._stack = QStackedWidget()
        self._home = HomePage()
        self._view = ViewPage(self._prefs)
        self._settings = SettingsPage()
        self._share = ShareController(self._prefs, parent=self)
        self._stack.addWidget(self._home)
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._settings)

        self._nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("Home", "View", "Settings")):
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
        self._home.start_sharing.connect(self._start_sharing_from_home)
        self._home.stop_sharing.connect(self._share.stop_sharing)
        self._home.reconnect_requested.connect(self._reconnect_from_history)
        self._settings.preferences_changed.connect(self._on_prefs_changed)
        self._share.approval_requested.connect(self._on_approval_requested)
        self._share.session_state_changed.connect(self._on_share_state)
        self._share.failed.connect(self._on_share_failed)
        self._share.finished.connect(self._on_share_finished)
        self._view.session_state_changed.connect(self._on_view_state)
        self._view.frame_ready.connect(self._on_view_frame)
        self._view.session_finished.connect(self._on_view_finished)
        self._view.session_failed.connect(self._on_view_failed)
        self._view.native_surface_requested.connect(self._prepare_native_view_surface)

        register_app_shutdown("persist-preferences", self._persist_preferences)
        register_app_shutdown("share-session-stop", self._share.stop_sharing)
        register_app_shutdown("view-session-stop", self._view.disconnect_session)
        self.statusBar().showMessage(
            "Home shows your address and recent connections — Settings configures sharing."
        )
        self._refresh_home_identity()
        self._goto(0)
        QTimer.singleShot(250, self._maybe_auto_start_share)

    def _refresh_home_identity(self) -> None:
        bind = self._share.resolve_bind_ip()
        port = int(getattr(self._prefs, "signaling_port", 3847))
        self._home.set_identity(bind_ip=bind, port=port)

    def _maybe_auto_start_share(self) -> None:
        if not bool(getattr(self._prefs, "auto_start_share", True)):
            return
        if self._share.is_running:
            return
        self._start_sharing_from_home()

    def _start_sharing_from_home(self) -> None:
        ok, err = self._share.start_sharing()
        if not ok and err:
            QMessageBox.warning(self, "Share", err)
            self._home.set_sharing_running(False)
        elif ok:
            self._home.set_sharing_running(True)
            self._home.set_identity(
                bind_ip=self._share.resolve_bind_ip(),
                port=int(getattr(self._prefs, "signaling_port", 3847)),
                pairing_code="…",
            )

    def _on_approval_requested(self, info: object) -> None:
        if self._approval_open:
            return
        self._approval_open = True
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            self._goto(0)
            accepted = prompt_incoming_connection(self, info)
            if accepted:
                self._pending_share_peer = str(
                    getattr(info, "remote_addr", None) or "viewer"
                )
            self._share.respond_approval(accepted)
        finally:
            self._approval_open = False

    def _ensure_share_session_window(self) -> ShareSessionWindow:
        if self._share_session_window is None:
            win = ShareSessionWindow(on_stop=self._share.stop_sharing, parent=self)
            win.setWindowIcon(self.windowIcon())
            self._share_session_window = win
        return self._share_session_window

    def _close_share_session_window(self, *, invoke_stop: bool = False) -> None:
        win = self._share_session_window
        self._share_session_window = None
        if win is not None:
            if not invoke_stop:
                win._on_stop = None  # noqa: SLF001
            win.close()

    def _ensure_view_session_window(self) -> ViewSessionWindow:
        if self._view_session_window is None:
            win = ViewSessionWindow(
                on_disconnect=self._view.disconnect_session,
                on_mute_changed=self._view.set_muted,
                parent=self,
            )
            win.setWindowIcon(self.windowIcon())
            win.native_video_surface.surface_changed.connect(self._view.native_surface_changed)
            win.native_video_surface.input_event.connect(self._view.native_input_event)
            self._view_session_window = win
        return self._view_session_window

    def _prepare_native_view_surface(self) -> None:
        win = self._ensure_view_session_window()
        win.show()
        self._view.set_native_surface_handle(win.native_video_handle)

    def _close_view_session_window(self, *, invoke_disconnect: bool = False) -> None:
        win = self._view_session_window
        self._view_session_window = None
        if win is not None:
            if not invoke_disconnect:
                win._on_disconnect = None  # noqa: SLF001
            win.close()

    def _record_share_connected(self, state: object) -> None:
        if self._active_share_history is not None:
            return
        peer = self._pending_share_peer or "viewer"
        port = int(getattr(state, "port", None) or self._prefs.signaling_port)
        entry = SessionHistoryEntry(
            role="share",
            peer=peer,
            port=port,
            started_at=utc_now_iso(),
            outcome="connected",
        )
        self._active_share_history = entry
        prepend_history(entry)
        self._home.reload_history()

    def _finalize_share_history(self, *, outcome: str) -> None:
        entry = self._active_share_history
        self._active_share_history = None
        self._pending_share_peer = None
        if entry is None:
            return
        entry.ended_at = utc_now_iso()
        entry.outcome = outcome
        # Rewrite newest entry with end time.
        from snowlink.session_history import load_history, save_history

        entries = load_history()
        if entries and entries[0].started_at == entry.started_at:
            entries[0] = entry
            save_history(entries)
        self._home.reload_history()

    def _record_view_connected(self, state: object) -> None:
        if self._active_view_history is not None:
            return
        peer = str(getattr(state, "remote_ip", None) or self._view._ip.text().strip() or "—")  # noqa: SLF001
        port = int(getattr(state, "port", None) or self._prefs.signaling_port)
        entry = SessionHistoryEntry(
            role="view",
            peer=peer,
            port=port,
            started_at=utc_now_iso(),
            outcome="connected",
        )
        self._active_view_history = entry
        prepend_history(entry)
        self._home.reload_history()

    def _finalize_view_history(self, *, outcome: str) -> None:
        entry = self._active_view_history
        self._active_view_history = None
        if entry is None:
            return
        entry.ended_at = utc_now_iso()
        entry.outcome = outcome
        from snowlink.session_history import load_history, save_history

        entries = load_history()
        if entries and entries[0].started_at == entry.started_at:
            entries[0] = entry
            save_history(entries)
        self._home.reload_history()

    def _on_share_state(self, state: object) -> None:
        self._home.apply_session_state(state)
        phase = str(getattr(state, "phase", "") or "")
        if phase in {"sharing", "reconnecting", "negotiating"}:
            if phase == "sharing":
                self._record_share_connected(state)
            win = self._ensure_share_session_window()
            win.update_state(state)
            win.show()
            win.raise_()
        elif phase in {"idle", "stopped", "failed", "stopping", "waiting_for_viewer"}:
            self._close_share_session_window(invoke_stop=False)
        elif self._share_session_window is not None:
            self._share_session_window.update_state(state)

    def _on_share_failed(self, message: str) -> None:
        self._finalize_share_history(outcome="failed")
        self._home.apply_session_state(None)
        self._refresh_home_identity()
        self._close_share_session_window(invoke_stop=False)
        QMessageBox.critical(self, "Share failed", message)

    def _on_share_finished(self, state: object) -> None:
        phase = str(getattr(state, "phase", "") or "") if state is not None else ""
        error = str(getattr(state, "error", "") or "").strip() if state is not None else ""
        if phase == "failed" or error:
            self._finalize_share_history(outcome="failed")
            self._home.apply_session_state(None)
            self._refresh_home_identity()
            self._close_share_session_window(invoke_stop=False)
            QMessageBox.critical(
                self,
                "Share failed",
                error or "Sharing stopped unexpectedly. Check Settings → Capture backend (try DXGI).",
            )
            return
        self._finalize_share_history(outcome="ended")
        self._home.apply_session_state(None)
        self._refresh_home_identity()
        self._close_share_session_window(invoke_stop=False)

    def _on_view_state(self, state: object) -> None:
        phase = str(getattr(state, "phase", "") or "")
        if phase in {"connecting", "pairing", "negotiating", "viewing", "reconnecting"}:
            if phase == "viewing":
                self._record_view_connected(state)
            win = self._ensure_view_session_window()
            win.update_state(state)
            win.show()
            win.raise_()
        elif phase in {"idle", "stopped", "failed", "stopping"} or state is None:
            self._close_view_session_window(invoke_disconnect=False)

    def _on_view_finished(self) -> None:
        self._finalize_view_history(outcome="ended")
        self._close_view_session_window(invoke_disconnect=False)

    def _on_view_failed(self, _message: str) -> None:
        self._finalize_view_history(outcome="failed")
        self._close_view_session_window(invoke_disconnect=False)

    def _on_view_frame(self, image: object) -> None:
        win = self._ensure_view_session_window()
        if not win.isVisible():
            win.show()
        try:
            win.show_frame(image)  # type: ignore[arg-type]
        finally:
            self._view.mark_frame_consumed()

    def _reconnect_from_history(self, entry: object) -> None:
        if not isinstance(entry, SessionHistoryEntry) or entry.role != "view":
            return
        peer = entry.peer
        if peer.count(":") == 1 and peer.split(":")[-1].isdigit():
            ip = peer.split(":", 1)[0]
        else:
            ip = peer
        self._prefs.last_remote_ip = ip
        self._prefs.signaling_port = int(entry.port)
        self._view.apply_preferences(self._prefs)
        self._view._ip.setText(ip)  # noqa: SLF001
        self._view._code.clear()  # noqa: SLF001
        self._goto(1)
        self.statusBar().showMessage(
            f"Reconnecting to {ip}:{entry.port} — enter the current pairing code.",
            8000,
        )

    def _persist_preferences(self) -> None:
        geo = self.geometry()
        self._prefs.window_x = int(geo.x())
        self._prefs.window_y = int(geo.y())
        self._prefs.window_width = int(geo.width())
        self._prefs.window_height = int(geo.height())
        try:
            remote = self._view._ip.text().strip()  # noqa: SLF001
            if remote:
                self._prefs.last_remote_ip = remote
        except Exception:
            pass
        try:
            save_preferences(self._prefs)
        except Exception:
            pass

    def _on_prefs_changed(self, prefs: UserPreferences) -> None:
        self._prefs = prefs
        self._share.apply_preferences(prefs)
        self._view.apply_preferences(prefs)
        self._refresh_home_identity()

    def _goto(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _goto_name(self, name: str) -> None:
        mapping = {
            "home": 0,
            "view": 1,
            "settings": 2,
            # Legacy aliases from older UI copy
            "share": 0,
            "diagnostics": 2,
        }
        self._goto(mapping.get(name.lower(), 0))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt API
        self._close_share_session_window()
        self._close_view_session_window()
        run_app_shutdown()
        super().closeEvent(event)
