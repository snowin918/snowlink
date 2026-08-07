"""Share page — local preview + LAN screen share (+ system audio + pairing)."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from snowlink.ui.argv_builders import PRESETS, build_experiment_c_argv
from snowlink.ui.paths import app_workdir, experiment_script
from snowlink.ui.widgets.stats_panel import StatsPanel
from snowlink.ui.workers import AsyncioSessionWorker, ExperimentProcessRunner


class SharePage(QWidget):
    def __init__(self, preferences: Any | None = None) -> None:
        super().__init__()
        self._preferences = preferences
        self._runner = ExperimentProcessRunner(self)
        self._runner.output.connect(self._on_output)
        self._runner.finished.connect(self._on_finished)
        self._runner.started.connect(self._on_started)

        self._session = AsyncioSessionWorker(self)
        self._session.state_changed.connect(self._on_session_state)
        self._session.finished.connect(self._on_session_finished)
        self._session.failed.connect(self._on_session_failed)
        self._session.approval_requested.connect(self._on_approval_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Share This Computer")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        warn = QLabel(
            "Screen + system-audio share with WebSocket pairing. Bind to a physical "
            "LAN IP. Approve the viewer when they present the 6-digit code."
        )
        warn.setObjectName("warningBanner")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        form_box = QGroupBox("Share settings")
        form = QFormLayout(form_box)

        self._adapter = QComboBox()
        self._adapter.setMinimumWidth(360)
        form.addRow("Network adapter", self._adapter)

        self._monitor = QComboBox()
        form.addRow("Monitor", self._monitor)

        self._audio_device = QComboBox()
        self._audio_device.setMinimumWidth(360)
        form.addRow("System audio (loopback)", self._audio_device)

        self._enable_audio = QCheckBox("Share system audio")
        self._enable_audio.setChecked(True)
        form.addRow("", self._enable_audio)

        self._preset = QComboBox()
        self._preset.addItems(list(PRESETS))
        self._preset.setCurrentText("low")
        form.addRow("Quality preset", self._preset)

        self._backend = QComboBox()
        self._backend.addItems(["dxgi", "winrt"])
        form.addRow("Capture backend", self._backend)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(3847)
        form.addRow("Signaling port", self._port)

        self._code_label = QLabel("—")
        self._code_label.setObjectName("pairingCode")
        form.addRow("Pairing code", self._code_label)

        self._sharing_indicator = QLabel("")
        self._sharing_indicator.setObjectName("sharingIndicator")
        self._sharing_indicator.setVisible(False)
        form.addRow("", self._sharing_indicator)

        layout.addWidget(form_box)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh adapters / monitors")
        refresh.clicked.connect(self.refresh_devices)
        row.addWidget(refresh)

        self._preview_btn = QPushButton("Start local preview")
        self._preview_btn.clicked.connect(self._start_preview)
        row.addWidget(self._preview_btn)

        self._stop_preview_btn = QPushButton("Stop preview")
        self._stop_preview_btn.setEnabled(False)
        self._stop_preview_btn.clicked.connect(self._runner.stop)
        row.addWidget(self._stop_preview_btn)

        self._share_btn = QPushButton("Start Sharing")
        self._share_btn.setObjectName("primaryButton")
        self._share_btn.clicked.connect(self._start_sharing)
        row.addWidget(self._share_btn)

        self._stop_share_btn = QPushButton("Stop Sharing")
        self._stop_share_btn.setEnabled(False)
        self._stop_share_btn.clicked.connect(self._session.stop)
        row.addWidget(self._stop_share_btn)

        self._approve_btn = QPushButton("Approve viewer")
        self._approve_btn.setEnabled(False)
        self._approve_btn.clicked.connect(lambda: self._session.respond_approval(True))
        row.addWidget(self._approve_btn)

        self._deny_btn = QPushButton("Deny")
        self._deny_btn.setEnabled(False)
        self._deny_btn.clicked.connect(lambda: self._session.respond_approval(False))
        row.addWidget(self._deny_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._status = QLabel("Ready.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._stats = StatsPanel()
        layout.addWidget(self._stats)
        layout.addStretch(1)

        self.refresh_devices()
        self.apply_preferences(self._preferences)

    def apply_preferences(self, prefs: Any | None) -> None:
        self._preferences = prefs
        if prefs is None:
            return
        try:
            self._port.setValue(int(getattr(prefs, "signaling_port", 3847)))
            preset = str(getattr(prefs, "preset", "low"))
            idx = self._preset.findText(preset)
            if idx >= 0:
                self._preset.setCurrentIndex(idx)
            backend = str(getattr(prefs, "backend", "dxgi"))
            bidx = self._backend.findText(backend)
            if bidx >= 0:
                self._backend.setCurrentIndex(bidx)
            self._enable_audio.setChecked(bool(getattr(prefs, "enable_audio", True)))
            monitor = int(getattr(prefs, "share_monitor", 0))
            for i in range(self._monitor.count()):
                if self._monitor.itemData(i) == monitor:
                    self._monitor.setCurrentIndex(i)
                    break
            bind_ip = getattr(prefs, "preferred_bind_ip", None)
            if bind_ip:
                for i in range(self._adapter.count()):
                    adapter = self._adapter.itemData(i)
                    addrs = getattr(adapter, "ipv4_addresses", None) or []
                    if any(str(a.address) == str(bind_ip) for a in addrs):
                        self._adapter.setCurrentIndex(i)
                        break
        except Exception:
            pass

    def refresh_devices(self) -> None:
        self._adapter.clear()
        self._monitor.clear()
        self._audio_device.clear()
        try:
            from snowlink.platform_win.adapters import enumerate_adapters, is_windows

            if is_windows():
                adapters = enumerate_adapters()
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
                    label = f"{adapter.friendly_name} [{cat}] - {ipv4s}"
                    self._adapter.addItem(label, adapter)
            else:
                self._adapter.addItem("(adapter list requires Windows)", None)
        except Exception as exc:  # noqa: BLE001 — show in UI
            self._adapter.addItem(f"(adapter error: {exc})", None)

        try:
            from snowlink.platform_win.monitors import enumerate_monitors, is_windows

            if is_windows():
                for monitor in enumerate_monitors():
                    primary = " primary" if monitor.is_primary else ""
                    label = (
                        f"{monitor.index}: {monitor.name} "
                        f"{monitor.width}x{monitor.height}{primary}"
                    )
                    self._monitor.addItem(label, int(monitor.index))
            else:
                self._monitor.addItem("0: (default)", 0)
        except Exception as exc:  # noqa: BLE001
            self._monitor.addItem(f"0: (monitor error: {exc})", 0)
            self._status.setText(f"Monitor enumeration failed: {exc}")

        if self._monitor.count() == 0:
            self._monitor.addItem("0", 0)

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
                if not getattr(ep, "is_loopback", False) or not getattr(ep, "can_capture", False):
                    continue
                flags: list[str] = []
                assoc_idx = getattr(ep, "associated_output_index", None)
                if default_out_idx is not None and assoc_idx == default_out_idx:
                    flags.append("ACTIVE OUTPUT")
                flag_s = f" [{', '.join(flags)}]" if flags else ""
                label = f"{ep.index}: {ep.name}{flag_s}"
                self._audio_device.addItem(label, str(ep.index))
        except Exception as exc:  # noqa: BLE001
            self._status.setText(f"Audio endpoint list unavailable: {exc}")

    def _selected_bind_ip(self) -> str | None:
        adapter = self._adapter.currentData()
        if adapter is None:
            return None
        addrs = getattr(adapter, "ipv4_addresses", None) or []
        if not addrs:
            return None
        return str(addrs[0].address)

    def _start_preview(self) -> None:
        if self._runner.is_running or self._session.is_running:
            QMessageBox.warning(self, "Busy", "Stop the current session first.")
            return
        monitor = self._monitor.currentData()
        monitor_index = int(monitor) if monitor is not None else 0
        try:
            from snowlink.media.capture_models import PRESETS as CAP_PRESETS

            preset_name = self._preset.currentText()
            preset = CAP_PRESETS[preset_name]  # type: ignore[index]
            argv = build_experiment_c_argv(
                "preview",
                monitor=monitor_index,
                backend=self._backend.currentText(),
                fps=preset.fps,
                width=preset.width,
                height=preset.height,
                duration=3600,
                no_preview=False,
            )
            script = experiment_script("experiment_c_screen_capture.py")
            self._runner.start(script, argv, working_directory=app_workdir())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Preview failed", str(exc))

    def _start_sharing(self) -> None:
        if self._runner.is_running or self._session.is_running:
            QMessageBox.warning(self, "Busy", "Stop the current session first.")
            return
        bind_ip = self._selected_bind_ip()
        if not bind_ip:
            QMessageBox.warning(self, "No IP", "Select an adapter with an IPv4 address.")
            return
        confirm = QMessageBox.question(
            self,
            "Start sharing?",
            "Snowlink will capture this computer’s screen"
            + (" and system audio" if self._enable_audio.isChecked() else "")
            + " and stream it to one approved viewer on the LAN.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        monitor = self._monitor.currentData()
        monitor_index = int(monitor) if monitor is not None else 0
        preset = self._preset.currentText()
        backend = self._backend.currentText()
        port = int(self._port.value())
        enable_audio = self._enable_audio.isChecked()
        audio_device = self._audio_device.currentData() or "default"
        worker = self._session

        def factory(stop_event: Any, on_state: Any, _on_frame: Any) -> Any:
            from snowlink.rtc.screen_session import (
                ScreenShareConfiguration,
                run_screen_share,
            )

            config = ScreenShareConfiguration.from_preset(
                bind_ip=bind_ip,
                signaling_port=port,
                monitor=monitor_index,
                backend=backend,  # type: ignore[arg-type]
                preset=preset,
                enable_audio=enable_audio,
                audio_capture_device=str(audio_device),
                auto_approve=False,
                approval_handler=worker.request_approval,
            )
            return run_screen_share(config, stop_event=stop_event, on_state=on_state)

        try:
            self._session.start(factory)
            self._share_btn.setEnabled(False)
            self._stop_share_btn.setEnabled(True)
            self._preview_btn.setEnabled(False)
            self._code_label.setText("…")
            media = "screen+audio" if enable_audio else "screen"
            self._status.setText(f"Starting {media} share on {bind_ip}:{port}...")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Share failed", str(exc))

    def _on_approval_requested(self, info: Any) -> None:
        remote = getattr(info, "remote_addr", "?")
        self._approve_btn.setEnabled(True)
        self._deny_btn.setEnabled(True)
        self._status.setText(f"Viewer from {remote} entered the code. Approve or Deny.")

    def _on_started(self, command: str) -> None:
        self._preview_btn.setEnabled(False)
        self._stop_preview_btn.setEnabled(True)
        self._share_btn.setEnabled(False)
        self._status.setText(f"Running: {command}")

    def _on_output(self, text: str) -> None:
        line = text.strip().splitlines()[-1] if text.strip() else ""
        if line:
            self._status.setText(line[:240])

    def _on_finished(self, code: int) -> None:
        self._preview_btn.setEnabled(True)
        self._stop_preview_btn.setEnabled(False)
        self._share_btn.setEnabled(True)
        self._status.setText(f"Preview exited with code {code}.")

    def _on_session_state(self, state: Any) -> None:
        code = getattr(state, "pairing_code", None)
        if code:
            self._code_label.setText(str(code))
        detail = getattr(state, "detail", "") or getattr(state, "phase", "")
        frames = getattr(state, "frames", 0)
        audio_frames = getattr(state, "audio_frames", 0)
        phase = getattr(state, "phase", "")
        self._status.setText(
            f"[{phase}] {detail} (video={frames}, audio={audio_frames})"
        )
        sharing = bool(getattr(state, "sharing_active", False)) or phase in {
            "waiting_for_viewer",
            "awaiting_approval",
            "negotiating",
            "sharing",
        }
        self._sharing_indicator.setVisible(sharing)
        if sharing:
            self._sharing_indicator.setText("● SHARING — this computer’s screen may be visible")
        self._stats.update_from_state(state)
        if phase != "awaiting_approval":
            self._approve_btn.setEnabled(False)
            self._deny_btn.setEnabled(False)

    def _on_session_finished(self, _state: Any) -> None:
        self._share_btn.setEnabled(True)
        self._stop_share_btn.setEnabled(False)
        self._preview_btn.setEnabled(True)
        self._approve_btn.setEnabled(False)
        self._deny_btn.setEnabled(False)
        self._code_label.setText("—")
        self._sharing_indicator.setVisible(False)
        self._stats.clear()
        self._status.setText("Sharing stopped.")

    def _on_session_failed(self, message: str) -> None:
        self._share_btn.setEnabled(True)
        self._stop_share_btn.setEnabled(False)
        self._preview_btn.setEnabled(True)
        self._approve_btn.setEnabled(False)
        self._deny_btn.setEnabled(False)
        self._sharing_indicator.setVisible(False)
        self._stats.clear()
        self._status.setText(message)
        QMessageBox.critical(self, "Share failed", message)
