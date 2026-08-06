"""View page — connect to a remote screen share (+ system audio)."""

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
from snowlink.ui.workers import AsyncioSessionWorker


class ViewPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._audio_controls = AudioPlaybackControls(muted=False, gain=0.25)
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
            "Remote screen + system audio (no pairing yet). Enter the sharer's LAN "
            "IP and signaling port. Keep playback gain low. Use only on your private LAN."
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
        self._code.setPlaceholderText("6-digit pairing code (Phase 3)")
        self._code.setMaxLength(6)
        self._code.setEnabled(False)
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

        self._video = QLabel("No video yet.")
        self._video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video.setMinimumHeight(280)
        self._video.setStyleSheet("background:#0f172a; color:#94a3b8; border-radius:8px;")
        layout.addWidget(self._video, stretch=1)

        self._status = QLabel("Ready.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._refresh_playback_devices()

    def _refresh_playback_devices(self) -> None:
        self._playback_device.clear()
        self._playback_device.addItem("default", "default")
        try:
            from snowlink.platform_win.audio_endpoints import enumerate_audio_endpoints

            for ep in enumerate_audio_endpoints():
                if not getattr(ep, "can_playback", False):
                    continue
                if getattr(ep, "is_loopback", False):
                    continue
                label = f"{ep.index}: {ep.name}"
                self._playback_device.addItem(label, str(ep.index))
        except Exception:
            pass

    def _on_mute_toggled(self, checked: bool) -> None:
        self._audio_controls.muted = bool(checked)

    def _connect(self) -> None:
        if self._session.is_running:
            QMessageBox.warning(self, "Busy", "Already connected or connecting.")
            return
        remote_ip = self._ip.text().strip()
        if not remote_ip:
            QMessageBox.warning(self, "Missing IP", "Enter the sharer's LAN IPv4 address.")
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
            self._status.setText(f"Connecting to {remote_ip}:{port}...")
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
        self._status.setText(
            f"[{phase}] {detail} (video={frames}, audio={audio_frames}, "
            f"underruns={underruns}, {mute_s})"
        )

    def _on_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self._video.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._video.setPixmap(scaled)

    def _on_session_finished(self, _state: Any) -> None:
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._status.setText("Disconnected.")

    def _on_session_failed(self, message: str) -> None:
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._status.setText(message)
        QMessageBox.critical(self, "View failed", message)
