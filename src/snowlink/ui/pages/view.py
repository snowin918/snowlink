"""View page — connect to a remote screen share (+ system audio + pairing)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from snowlink.media.audio_track import AudioPlaybackControls
from snowlink.ui.widgets.stats_panel import StatsPanel
from snowlink.ui.workers import AsyncioSessionWorker


class ViewPage(QWidget):
    def __init__(self, preferences: Any | None = None) -> None:
        super().__init__()
        self._preferences = preferences
        self._audio_controls = AudioPlaybackControls(muted=False, gain=1.0)
        self._session = AsyncioSessionWorker(self)
        self._session.state_changed.connect(self._on_session_state)
        self._session.frame_ready.connect(self._on_frame)
        self._session.finished.connect(self._on_session_finished)
        self._session.failed.connect(self._on_session_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("View Another Computer")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        warn = QLabel(
            "Enter the sharer's LAN IP, port, and 6-digit pairing code. Use "
            "default/WASAPI speakers or headphones. Unmute; keep Windows volume up."
        )
        warn.setObjectName("warningBanner")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        box = QGroupBox("Connection")
        form = QFormLayout(box)
        self._ip = QLineEdit()
        self._ip.setPlaceholderText("192.168.1.25")
        form.addRow("Remote IP", self._ip)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(3847)
        form.addRow("Port", self._port)

        self._source_ip = QLineEdit()
        self._source_ip.setPlaceholderText("optional local LAN IPv4")
        form.addRow("Source IP", self._source_ip)

        self._playback_device = QComboBox()
        self._playback_device.setMinimumWidth(280)
        form.addRow("Playback device", self._playback_device)

        self._enable_audio = QCheckBox("Play remote system audio")
        self._enable_audio.setChecked(True)
        form.addRow("", self._enable_audio)

        self._mute = QCheckBox("Mute")
        self._mute.setChecked(False)
        self._mute.toggled.connect(self._on_mute_toggled)
        form.addRow("", self._mute)

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

        self._fullscreen_btn = QPushButton("Fullscreen")
        self._fullscreen_btn.setEnabled(False)
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._fullscreen_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._video = QLabel("No video yet.")
        self._video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video.setMinimumHeight(280)
        self._video.setStyleSheet("background:#0f172a; color:#94a3b8; border-radius:8px;")
        layout.addWidget(self._video, stretch=1)

        self._fullscreen_window: QWidget | None = None
        self._fullscreen_label: QLabel | None = None
        self._last_pixmap: QPixmap | None = None

        self._status = QLabel("Ready.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._stats = StatsPanel()
        layout.addWidget(self._stats)

        self._refresh_playback_devices()
        self.apply_preferences(self._preferences)

    def apply_preferences(self, prefs: Any | None) -> None:
        self._preferences = prefs
        if prefs is None:
            return
        try:
            self._port.setValue(int(getattr(prefs, "signaling_port", 3847)))
            remote = getattr(prefs, "last_remote_ip", None)
            if remote:
                self._ip.setText(str(remote))
            source = getattr(prefs, "last_source_ip", None)
            if source:
                self._source_ip.setText(str(source))
            self._enable_audio.setChecked(bool(getattr(prefs, "enable_audio", True)))
        except Exception:
            pass

    def _refresh_playback_devices(self) -> None:
        self._playback_device.clear()
        self._playback_device.addItem("default (WASAPI output)", "default")
        try:
            from snowlink.platform_win.audio_endpoints import enumerate_audio_endpoints

            for ep in enumerate_audio_endpoints():
                if not getattr(ep, "can_playback", False):
                    continue
                if getattr(ep, "is_loopback", False):
                    continue
                # Prefer WASAPI — MME/DirectSound duplicates confuse selection
                # and often produce silent or wrong-device output.
                if not getattr(ep, "is_wasapi", False):
                    continue
                flags = []
                if getattr(ep, "is_default_output", False):
                    flags.append("DEFAULT")
                flag_s = f" [{', '.join(flags)}]" if flags else ""
                label = f"{ep.index}: {ep.name} (WASAPI){flag_s}"
                self._playback_device.addItem(label, str(ep.index))
        except Exception:
            pass

    def _on_mute_toggled(self, checked: bool) -> None:
        self._audio_controls.muted = bool(checked)

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen_window is not None and self._fullscreen_window.isVisible():
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
            self._fullscreen_btn.setText("Fullscreen")
            return
        win = QWidget()
        win.setWindowTitle("Snowlink — Fullscreen")
        win.setStyleSheet("background:#000;")
        lay = QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label)
        if self._last_pixmap is not None:
            label.setPixmap(
                self._last_pixmap.scaled(
                    win.screen().availableGeometry().size()
                    if win.screen() is not None
                    else self._video.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        win.showFullScreen()
        self._fullscreen_window = win
        self._fullscreen_label = label
        self._fullscreen_btn.setText("Exit fullscreen")

    def _connect(self) -> None:
        if self._session.is_running:
            QMessageBox.warning(self, "Busy", "Already connected or connecting.")
            return
        remote_ip = self._ip.text().strip()
        if not remote_ip:
            QMessageBox.warning(self, "Missing IP", "Enter the sharer's LAN IPv4 address.")
            return
        code = self._code.text().strip()
        if not code.isdigit() or len(code) != 6:
            QMessageBox.warning(self, "Pairing code", "Enter the 6-digit pairing code.")
            return
        port = int(self._port.value())
        source = self._source_ip.text().strip() or None
        enable_audio = self._enable_audio.isChecked()
        playback_device = self._playback_device.currentData() or "default"
        self._audio_controls.muted = self._mute.isChecked()
        controls = self._audio_controls

        def factory(stop_event: Any, on_state: Any, on_frame: Any) -> Any:
            from snowlink.rtc.screen_session import (
                ScreenViewConfiguration,
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
            return run_screen_view(
                config,
                stop_event=stop_event,
                on_state=on_state,
                on_frame=on_frame,
            )

        try:
            self._session.start(factory)
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._fullscreen_btn.setEnabled(True)
            self._status.setText(f"Connecting to {remote_ip}:{port}…")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Connect failed", str(exc))

    def _on_session_state(self, state: Any) -> None:
        detail = getattr(state, "detail", "") or getattr(state, "phase", "")
        frames = getattr(state, "frames", 0)
        audio_frames = getattr(state, "audio_frames", 0)
        underruns = getattr(state, "audio_underruns", 0)
        muted = getattr(state, "muted", False)
        phase = getattr(state, "phase", "")
        mute_s = "muted" if muted else "audio"
        peak = None
        stats = getattr(state, "stats", None)
        if stats is not None:
            peak = getattr(stats, "audio_peak", None)
        peak_s = f", level={min(100.0, float(peak) * 100.0):.0f}%" if peak is not None else ""
        self._status.setText(
            f"[{phase}] {detail} (video={frames}, audio={audio_frames}, "
            f"underruns={underruns}{peak_s}, {mute_s})"
        )
        self._stats.update_from_state(state)

    def _on_frame(self, image: QImage) -> None:
        try:
            if image.isNull():
                return
            pixmap = QPixmap.fromImage(image)
            self._last_pixmap = pixmap
            scaled = pixmap.scaled(
                self._video.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._video.setPixmap(scaled)
            if self._fullscreen_label is not None and self._fullscreen_window is not None:
                self._fullscreen_label.setPixmap(
                    pixmap.scaled(
                        self._fullscreen_window.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                )
        finally:
            self._session.mark_frame_consumed()

    def _on_session_finished(self, _state: Any) -> None:
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._fullscreen_btn.setEnabled(False)
        self._fullscreen_btn.setText("Fullscreen")
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
        self._stats.clear()
        self._status.setText("Disconnected.")

    def _on_session_failed(self, message: str) -> None:
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._fullscreen_btn.setEnabled(False)
        self._fullscreen_btn.setText("Fullscreen")
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
        self._stats.clear()
        self._status.setText(message)
        QMessageBox.critical(self, "View failed", message)
