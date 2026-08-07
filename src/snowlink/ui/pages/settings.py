"""Settings page — persisted Share/View defaults."""

from __future__ import annotations

from PySide6.QtCore import Signal
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

from snowlink.config import UserPreferences, load_preferences, save_preferences
from snowlink.platform_win.paths import config_path
from snowlink.ui.argv_builders import PRESETS


class SettingsPage(QWidget):
    preferences_changed = Signal(object)  # UserPreferences

    def __init__(self) -> None:
        super().__init__()
        self._prefs = load_preferences()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(f"Saved to {config_path()}")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        box = QGroupBox("Defaults")
        form = QFormLayout(box)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        form.addRow("Signaling port", self._port)

        self._preset = QComboBox()
        self._preset.addItems(list(PRESETS))
        form.addRow("Quality preset", self._preset)

        self._backend = QComboBox()
        self._backend.addItems(["dxgi", "winrt"])
        form.addRow("Capture backend", self._backend)

        self._enable_audio = QCheckBox("Share / play system audio by default")
        form.addRow("", self._enable_audio)

        self._bind_ip = QLineEdit()
        self._bind_ip.setPlaceholderText("optional preferred LAN IPv4")
        form.addRow("Preferred bind IP", self._bind_ip)

        self._remote_ip = QLineEdit()
        self._remote_ip.setPlaceholderText("last remote viewer target")
        form.addRow("Last remote IP", self._remote_ip)

        self._monitor = QSpinBox()
        self._monitor.setRange(0, 15)
        form.addRow("Default monitor index", self._monitor)

        layout.addWidget(box)

        row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.reload_from_disk)
        row.addWidget(reload_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

        self._apply_to_form(self._prefs)

    def preferences(self) -> UserPreferences:
        return self._prefs

    def reload_from_disk(self) -> None:
        self._prefs = load_preferences()
        self._apply_to_form(self._prefs)

    def _apply_to_form(self, prefs: UserPreferences) -> None:
        self._port.setValue(int(prefs.signaling_port))
        idx = self._preset.findText(prefs.preset)
        if idx >= 0:
            self._preset.setCurrentIndex(idx)
        bidx = self._backend.findText(prefs.backend)
        if bidx >= 0:
            self._backend.setCurrentIndex(bidx)
        self._enable_audio.setChecked(bool(prefs.enable_audio))
        self._bind_ip.setText(prefs.preferred_bind_ip or "")
        self._remote_ip.setText(prefs.last_remote_ip or "")
        self._monitor.setValue(int(prefs.share_monitor))

    def _collect(self) -> UserPreferences:
        return UserPreferences(
            signaling_port=int(self._port.value()),
            preset=self._preset.currentText(),
            backend=self._backend.currentText(),
            enable_audio=self._enable_audio.isChecked(),
            preferred_adapter_name=self._prefs.preferred_adapter_name,
            preferred_bind_ip=self._bind_ip.text().strip() or None,
            last_remote_ip=self._remote_ip.text().strip() or None,
            last_source_ip=self._prefs.last_source_ip,
            share_monitor=int(self._monitor.value()),
            window_x=self._prefs.window_x,
            window_y=self._prefs.window_y,
            window_width=self._prefs.window_width,
            window_height=self._prefs.window_height,
        )

    def _save(self) -> None:
        try:
            self._prefs = self._collect()
            path = save_preferences(self._prefs)
            self.preferences_changed.emit(self._prefs)
            QMessageBox.information(self, "Saved", f"Preferences written to:\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
