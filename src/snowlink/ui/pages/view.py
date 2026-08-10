"""View page — connect to a remote screen share (video opens in a session window)."""

from __future__ import annotations

import sys
import threading
from typing import Any, cast

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snowlink.media.audio_models import AudioPlaybackControls
from snowlink.ui.widgets.collapsible import wrap_in_scroll
from snowlink.ui.widgets.stats_panel import StatsPanel
from snowlink.ui.workers import AsyncioSessionWorker

_PHASE_STATUS: dict[str, str] = {
    "idle": "Ready.",
    "connecting": "Connecting…",
    "pairing": "Checking pairing code…",
    "negotiating": "Connecting…",
    "viewing": "Connected — video opens in a separate window.",
    "reconnecting": "Reconnecting…",
    "stopping": "Disconnecting…",
    "failed": "Connection failed.",
}


class ViewPage(QWidget):
    session_state_changed = Signal(object)
    frame_ready = Signal(object)  # QImage
    session_finished = Signal()
    session_failed = Signal(str)
    native_surface_requested = Signal()

    def __init__(self, preferences: Any | None = None) -> None:
        super().__init__()
        self._preferences = preferences
        self._native_surface_handle = 0
        self._native_engine: Any | None = None
        self._native_mouse_lock = threading.Lock()
        self._native_mouse_pending: dict[str, Any] | None = None
        self._native_mouse_scheduled = False
        self._audio_controls = AudioPlaybackControls(muted=False, gain=1.0)
        self._session = AsyncioSessionWorker(self)
        self._session.state_changed.connect(self._on_session_state)
        self._session.frame_ready.connect(self._on_frame)
        self._session.finished.connect(self._on_session_finished)
        self._session.failed.connect(self._on_session_failed)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("View Another Computer")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        tip = QLabel(
            "Enter the other PC’s address and the 6-digit pairing code. "
            "After they Accept, the remote screen opens in a separate window. "
            "Port and source IP are under Settings."
        )
        tip.setObjectName("warningBanner")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        box = QGroupBox("Connection")
        form = QFormLayout(box)
        self._ip = QLineEdit()
        self._ip.setPlaceholderText("e.g. 192.168.1.25")
        form.addRow("Other PC’s address", self._ip)

        self._code = QLineEdit()
        self._code.setPlaceholderText("6-digit pairing code")
        self._code.setMaxLength(6)
        form.addRow("Pairing code", self._code)
        layout.addWidget(box)

        row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("primaryButton")
        self._connect_btn.clicked.connect(self._connect)
        row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._session.stop)
        row.addWidget(self._disconnect_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._status = QLabel("Ready.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._stats = StatsPanel(collapsed=True)
        layout.addWidget(self._stats)
        layout.addStretch(1)

        wrap_in_scroll(self, content)
        self.apply_preferences(self._preferences)

    def apply_preferences(self, prefs: Any | None) -> None:
        self._preferences = prefs
        if prefs is None:
            return
        try:
            remote = getattr(prefs, "last_remote_ip", None)
            if remote:
                self._ip.setText(str(remote))
        except Exception:
            pass

    def set_muted(self, muted: bool) -> None:
        self._audio_controls.muted = bool(muted)

    def disconnect_session(self) -> None:
        self._session.stop()

    def mark_frame_consumed(self) -> None:
        self._session.mark_frame_consumed()

    def set_native_surface_handle(self, hwnd: int) -> None:
        self._native_surface_handle = int(hwnd)

    def native_surface_changed(self, visible: bool) -> None:
        engine = self._native_engine
        if engine is None:
            return
        active_engine: Any = cast(Any, engine)

        def apply_surface_change() -> None:
            if active_engine is not self._native_engine:
                return
            assert active_engine is not None
            try:
                active_engine.receiver_set_visible(visible)
                if visible:
                    active_engine.receiver_resize()
            except Exception:
                pass

        self._session.dispatch(apply_surface_change)

    def native_input_event(self, event: dict[str, Any]) -> None:
        engine = self._native_engine
        if engine is None:
            return
        active_engine: Any = cast(Any, engine)

        # Mouse tracking can produce hundreds of moves per second. Keep only
        # the newest move while one worker callback is queued so neither Qt nor
        # the asyncio control loop develops an unbounded event backlog.
        if event.get("kind") == 1:
            with self._native_mouse_lock:
                self._native_mouse_pending = dict(event)
                if self._native_mouse_scheduled:
                    return
                self._native_mouse_scheduled = True
            if not self._session.dispatch(self._drain_native_mouse):
                with self._native_mouse_lock:
                    self._native_mouse_scheduled = False
            return

        payload = dict(event)

        def send_discrete_input() -> None:
            if active_engine is not self._native_engine:
                return
            assert active_engine is not None
            try:
                active_engine.send_input(**payload)
            except Exception:
                pass

        self._session.dispatch(send_discrete_input)

    def _drain_native_mouse(self) -> None:
        with self._native_mouse_lock:
            event = self._native_mouse_pending
            self._native_mouse_pending = None
            self._native_mouse_scheduled = False
        engine = self._native_engine
        if engine is None or event is None:
            return
        try:
            status = engine.decoder_status()
            sw = int(status["decoded_width"])
            sh = int(status["decoded_height"])
            dw = max(1, int(event["width"]))
            dh = max(1, int(event["height"]))
            scale = min(dw / sw, dh / sh) if sw and sh else 1.0
            ox = (dw - sw * scale) / 2
            oy = (dh - sh * scale) / 2
            x = max(0, min(sw - 1, int((event["x"] - ox) / scale)))
            y = max(0, min(sh - 1, int((event["y"] - oy) / scale)))
            engine.send_input(kind=1, x=x, y=y)
        except Exception:
            pass

    def _connect(self) -> None:
        if self._session.is_running:
            QMessageBox.warning(self, "Busy", "Already connected or connecting.")
            return
        media_backend = str(getattr(self._preferences, "media_backend", "native_cpp"))
        if getattr(sys, "frozen", False):
            media_backend = "native_cpp"
        if media_backend == "native_cpp":
            self.native_surface_requested.emit()
        remote_ip = self._ip.text().strip()
        if not remote_ip:
            QMessageBox.warning(self, "Missing address", "Enter the other PC’s address.")
            return
        code = self._code.text().strip()
        if not code.isdigit() or len(code) != 6:
            QMessageBox.warning(self, "Pairing code", "Enter the 6-digit pairing code.")
            return
        prefs = self._preferences
        port = int(getattr(prefs, "signaling_port", 3847) if prefs else 3847)
        source = getattr(prefs, "last_source_ip", None) if prefs else None
        if isinstance(source, str):
            source = source.strip() or None
        enable_audio = bool(getattr(prefs, "enable_audio", True) if prefs else True)
        playback_device = "default"
        self._audio_controls.muted = False
        controls = self._audio_controls

        def factory(stop_event: Any, on_state: Any, on_frame: Any) -> Any:
            from snowlink.rtc.screen_session import (
                ScreenViewConfiguration,
                run_native_screen_view,
                run_screen_view,
            )

            config = ScreenViewConfiguration(
                remote_ip=remote_ip,
                pairing_code=code,
                signaling_port=port,
                requested_source_ip=source,
                preview=False,
                enable_audio=enable_audio,
                playback=enable_audio,
                playback_device=str(playback_device),
                muted=controls.muted,
                gain=controls.gain,
                playback_controls=controls,
            )
            if media_backend == "native_cpp":
                if not self._native_surface_handle:
                    raise RuntimeError("Native video surface is unavailable")
                return run_native_screen_view(
                    config,
                    hwnd=self._native_surface_handle,
                    stop_event=stop_event,
                    on_state=on_state,
                    on_engine=lambda engine: setattr(self, "_native_engine", engine),
                )
            return run_screen_view(
                config, stop_event=stop_event, on_state=on_state, on_frame=on_frame
            )

        try:
            self._session.start(factory)
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._status.setText("Connecting…")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Connect failed", str(exc))

    def _friendly_status(self, state: Any) -> str:
        phase = str(getattr(state, "phase", "") or "")
        detail = str(getattr(state, "detail", "") or "").strip()
        mapped = _PHASE_STATUS.get(phase)
        if mapped:
            if phase == "viewing" and getattr(state, "muted", False):
                return "Connected (muted)."
            return mapped
        if detail:
            return detail
        return phase or "Ready."

    def _on_session_state(self, state: Any) -> None:
        self._status.setText(self._friendly_status(state))
        self._stats.update_from_state(state)
        self.session_state_changed.emit(state)

    def _on_frame(self, image: QImage) -> None:
        self.frame_ready.emit(image)

    def _on_session_finished(self, _state: Any) -> None:
        self._native_engine = None
        with self._native_mouse_lock:
            self._native_mouse_pending = None
            self._native_mouse_scheduled = False
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._stats.clear()
        self._status.setText("Disconnected.")
        self.session_finished.emit()

    def _on_session_failed(self, message: str) -> None:
        self._native_engine = None
        with self._native_mouse_lock:
            self._native_mouse_pending = None
            self._native_mouse_scheduled = False
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._stats.clear()
        self._status.setText(message)
        self.session_failed.emit(message)
        QMessageBox.critical(self, "View failed", message)
