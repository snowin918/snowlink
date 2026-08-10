"""Settings page — persisted Share/View defaults and advanced options."""

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
from snowlink.ui.argv_builders import populate_preset_combo, preset_from_combo
from snowlink.ui.widgets.collapsible import wrap_in_scroll


class SettingsPage(QWidget):
    preferences_changed = Signal(object)  # UserPreferences

    def __init__(self) -> None:
        super().__init__()
        self._prefs = load_preferences()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            f"Saved to {config_path()}. These options apply when Snowlink starts sharing."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        box = QGroupBox("Sharing defaults")
        form = QFormLayout(box)

        self._auto_start = QCheckBox("Start sharing when Snowlink opens")
        self._auto_start.setChecked(True)
        form.addRow("", self._auto_start)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        form.addRow("Signaling port", self._port)

        self._preset = QComboBox()
        populate_preset_combo(self._preset, current="low")
        form.addRow("Quality", self._preset)

        self._enable_audio = QCheckBox("Share / play system audio by default")
        form.addRow("", self._enable_audio)

        self._monitor = QComboBox()
        form.addRow("Which screen", self._monitor)

        self._audio_device = QComboBox()
        form.addRow("System audio device", self._audio_device)

        layout.addWidget(box)

        net = QGroupBox("Network")
        net_form = QFormLayout(net)

        self._adapter = QComboBox()
        self._adapter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._adapter.currentIndexChanged.connect(self._on_adapter_changed)
        net_form.addRow("Network adapter", self._adapter)

        self._bind_ip = QComboBox()
        net_form.addRow("Bind IPv4", self._bind_ip)

        self._remote_ip = QLineEdit()
        self._remote_ip.setPlaceholderText("last remote viewer target")
        net_form.addRow("Last remote IP", self._remote_ip)

        self._source_ip = QLineEdit()
        self._source_ip.setPlaceholderText("optional local source IPv4 for View")
        net_form.addRow("Last source IP", self._source_ip)

        layout.addWidget(net)

        adv = QGroupBox("Advanced")
        adv_form = QFormLayout(adv)
        self._backend = QComboBox()
        self._backend.addItems(["dxgi", "winrt"])
        self._backend.setToolTip(
            "DXGI (recommended): no yellow capture border; best for portable .exe.\n"
            "WinRT: may show a Windows yellow border while sharing; needs WinRT "
            "packages in the build. Snowlink falls back to DXGI if WinRT is unavailable."
        )
        adv_form.addRow("Capture backend", self._backend)

        self._media_engine = QComboBox()
        self._media_engine.addItems(["legacy_python", "native_cpp"])
        self._media_engine.setToolTip(
            "Select the media engine lifetime. "
            "native_cpp only probes the native DLL lifecycle today; share/view sessions still use legacy_python until the native pipeline is implemented."
        )
        adv_form.addRow("Media engine", self._media_engine)
        layout.addWidget(adv)

        row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh adapters / devices")
        refresh_btn.clicked.connect(self.refresh_devices)
        row.addWidget(refresh_btn)
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

        wrap_in_scroll(self, content)

        self.refresh_devices()
        self._apply_to_form(self._prefs)

    def preferences(self) -> UserPreferences:
        return self._prefs

    def reload_from_disk(self) -> None:
        self._prefs = load_preferences()
        self.refresh_devices()
        self._apply_to_form(self._prefs)

    def refresh_devices(self) -> None:
        self._adapter.blockSignals(True)
        self._adapter.clear()
        self._bind_ip.clear()
        self._monitor.clear()
        self._audio_device.clear()
        try:
            from snowlink.net.adapter_selection import annotate_adapters
            from snowlink.platform_win.adapters import enumerate_adapters, is_windows

            if is_windows():
                adapters = annotate_adapters(enumerate_adapters())
                adapters = sorted(
                    adapters,
                    key=lambda a: (
                        0 if a.preferred else 1,
                        -int(a.preference_score),
                        a.friendly_name.lower(),
                    ),
                )
                for adapter in adapters:
                    ipv4s = (
                        ", ".join(a.address for a in adapter.ipv4_addresses)
                        or "(no IPv4)"
                    )
                    cat = (
                        adapter.category.value
                        if hasattr(adapter.category, "value")
                        else str(adapter.category)
                    )
                    marker = "★ " if adapter.preferred else ""
                    label = f"{marker}{adapter.friendly_name} [{cat}] - {ipv4s}"
                    self._adapter.addItem(label, adapter)
            else:
                self._adapter.addItem("(adapter list requires Windows)", None)
        except Exception as exc:  # noqa: BLE001
            self._adapter.addItem(f"(adapter error: {exc})", None)
        finally:
            self._adapter.blockSignals(False)

        self._on_adapter_changed()

        try:
            from snowlink.platform_win.monitors import enumerate_monitors, is_windows

            if is_windows():
                for monitor in enumerate_monitors():
                    primary = " (main)" if monitor.is_primary else ""
                    label = (
                        f"{monitor.name} "
                        f"{monitor.width}×{monitor.height}{primary}"
                    )
                    self._monitor.addItem(label, int(monitor.index))
            else:
                self._monitor.addItem("Default screen", 0)
        except Exception:
            self._monitor.addItem("Default screen", 0)
        if self._monitor.count() == 0:
            self._monitor.addItem("Default screen", 0)

        self._audio_device.addItem("default (system output loopback)", "default")
        try:
            from snowlink.platform_win.audio_endpoints import enumerate_audio_endpoints

            endpoints = enumerate_audio_endpoints()
            default_out_idx = next(
                (
                    ep.index
                    for ep in endpoints
                    if getattr(ep, "is_default_output", False)
                    and getattr(ep, "can_playback", False)
                ),
                None,
            )
            for ep in endpoints:
                if not getattr(ep, "is_loopback", False) or not getattr(
                    ep, "can_capture", False
                ):
                    continue
                flags: list[str] = []
                assoc_idx = getattr(ep, "associated_output_index", None)
                if default_out_idx is not None and assoc_idx == default_out_idx:
                    flags.append("ACTIVE OUTPUT")
                flag_s = f" [{', '.join(flags)}]" if flags else ""
                label = f"{ep.index}: {ep.name}{flag_s}"
                self._audio_device.addItem(label, str(ep.index))
        except Exception:
            pass

    def _on_adapter_changed(self, *_args: object) -> None:
        current_ip = self._bind_ip.currentData()
        self._bind_ip.clear()
        adapter = self._adapter.currentData()
        if adapter is None:
            return
        addrs = getattr(adapter, "ipv4_addresses", None) or []
        private_first = sorted(
            addrs,
            key=lambda a: (
                0
                if getattr(a, "is_private", False)
                and not getattr(a, "is_loopback", False)
                else 1,
                str(a.address),
            ),
        )
        for addr in private_first:
            label = str(addr.address)
            if getattr(addr, "is_private", False):
                label = f"{label} (private)"
            self._bind_ip.addItem(label, str(addr.address))
        if current_ip:
            idx = self._bind_ip.findData(str(current_ip))
            if idx >= 0:
                self._bind_ip.setCurrentIndex(idx)

    def _select_preferred_adapter_and_ip(self, prefs: UserPreferences) -> None:
        if self._adapter.count() == 0:
            return
        bind_ip = prefs.preferred_bind_ip
        adapter_name = prefs.preferred_adapter_name

        if bind_ip:
            for i in range(self._adapter.count()):
                adapter = self._adapter.itemData(i)
                addrs = getattr(adapter, "ipv4_addresses", None) or []
                if any(str(a.address) == str(bind_ip) for a in addrs):
                    self._adapter.setCurrentIndex(i)
                    self._on_adapter_changed()
                    ip_idx = self._bind_ip.findData(str(bind_ip))
                    if ip_idx >= 0:
                        self._bind_ip.setCurrentIndex(ip_idx)
                    return

        if adapter_name:
            for i in range(self._adapter.count()):
                adapter = self._adapter.itemData(i)
                if adapter is None:
                    continue
                if str(getattr(adapter, "friendly_name", "")) == str(adapter_name):
                    self._adapter.setCurrentIndex(i)
                    self._on_adapter_changed()
                    return

        try:
            from snowlink.net.adapter_selection import select_preferred_endpoint

            adapters = [
                self._adapter.itemData(i)
                for i in range(self._adapter.count())
                if self._adapter.itemData(i) is not None
            ]
            selected = select_preferred_endpoint(adapters)
            if selected is None:
                for i in range(self._adapter.count()):
                    adapter = self._adapter.itemData(i)
                    if adapter is not None and getattr(adapter, "preferred", False):
                        self._adapter.setCurrentIndex(i)
                        self._on_adapter_changed()
                        return
                if self._adapter.count() > 0:
                    self._adapter.setCurrentIndex(0)
                    self._on_adapter_changed()
                return
            for i in range(self._adapter.count()):
                adapter = self._adapter.itemData(i)
                if adapter is None:
                    continue
                if getattr(adapter, "adapter_id", None) == selected.adapter.adapter_id:
                    self._adapter.setCurrentIndex(i)
                    self._on_adapter_changed()
                    ip_idx = self._bind_ip.findData(str(selected.ipv4))
                    if ip_idx >= 0:
                        self._bind_ip.setCurrentIndex(ip_idx)
                    return
        except Exception:
            if self._adapter.count() > 0:
                self._adapter.setCurrentIndex(0)
                self._on_adapter_changed()

    def _apply_to_form(self, prefs: UserPreferences) -> None:
        self._auto_start.setChecked(bool(getattr(prefs, "auto_start_share", True)))
        self._port.setValue(int(prefs.signaling_port))
        populate_preset_combo(self._preset, current=str(prefs.preset))
        bidx = self._backend.findText(prefs.backend)
        if bidx >= 0:
            self._backend.setCurrentIndex(bidx)
        self._enable_audio.setChecked(bool(prefs.enable_audio))
        self._remote_ip.setText(prefs.last_remote_ip or "")
        self._source_ip.setText(prefs.last_source_ip or "")
        me_idx = self._media_engine.findText(prefs.media_engine)
        if me_idx >= 0:
            self._media_engine.setCurrentIndex(me_idx)
        for i in range(self._monitor.count()):
            if self._monitor.itemData(i) == int(prefs.share_monitor):
                self._monitor.setCurrentIndex(i)
                break
        audio = getattr(prefs, "audio_capture_device", None) or "default"
        aidx = self._audio_device.findData(str(audio))
        if aidx >= 0:
            self._audio_device.setCurrentIndex(aidx)
        self._select_preferred_adapter_and_ip(prefs)

    def _collect(self) -> UserPreferences:
        bind = self._bind_ip.currentData()
        adapter = self._adapter.currentData()
        adapter_name = None
        if adapter is not None:
            name = getattr(adapter, "friendly_name", None)
            if name:
                adapter_name = str(name)
        mon = self._monitor.currentData()
        audio = self._audio_device.currentData() or "default"
        return UserPreferences(
            signaling_port=int(self._port.value()),
            preset=preset_from_combo(self._preset),
            backend=self._backend.currentText(),
            enable_audio=self._enable_audio.isChecked(),
            preferred_adapter_name=adapter_name,
            preferred_bind_ip=str(bind) if bind else None,
            last_remote_ip=self._remote_ip.text().strip() or None,
            last_source_ip=self._source_ip.text().strip() or None,
            share_monitor=int(mon) if mon is not None else 0,
            audio_capture_device=str(audio),
            auto_start_share=self._auto_start.isChecked(),
            media_engine=self._media_engine.currentText(),
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
