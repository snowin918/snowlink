"""Share page — local preview + Phase 1 LAN screen share."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
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
from snowlink.ui.workers import AsyncioSessionWorker, ExperimentProcessRunner


class SharePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._runner = ExperimentProcessRunner(self)
        self._runner.output.connect(self._on_output)
        self._runner.finished.connect(self._on_finished)
        self._runner.started.connect(self._on_started)

        self._session = AsyncioSessionWorker(self)
        self._session.state_changed.connect(self._on_session_state)
        self._session.finished.connect(self._on_session_finished)
        self._session.failed.connect(self._on_session_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Share This Computer")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        warn = QLabel(
            "Phase 1 screen share (no pairing yet). HTTP signaling on the selected "
            "LAN IP — use only on your private LAN. System audio arrives in Phase 2."
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

        self._preset = QComboBox()
        self._preset.addItems(list(PRESETS))
        # Experiment C Balanced ~21 FPS on lab host; Low is the Phase 1 demo default.
        self._preset.setCurrentText("low")
        form.addRow("Quality preset", self._preset)

        self._backend = QComboBox()
        self._backend.addItems(["dxgi", "winrt"])
        form.addRow("Capture backend", self._backend)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(3847)
        form.addRow("Signaling port", self._port)

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
        row.addStretch(1)
        layout.addLayout(row)

        self._status = QLabel("Ready.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)

        self.refresh_devices()

    def refresh_devices(self) -> None:
        self._adapter.clear()
        self._monitor.clear()
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
        monitor = self._monitor.currentData()
        monitor_index = int(monitor) if monitor is not None else 0
        preset = self._preset.currentText()
        backend = self._backend.currentText()
        port = int(self._port.value())

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
            )
            return run_screen_share(config, stop_event=stop_event, on_state=on_state)

        try:
            self._session.start(factory)
            self._share_btn.setEnabled(False)
            self._stop_share_btn.setEnabled(True)
            self._preview_btn.setEnabled(False)
            self._status.setText(f"Starting share on {bind_ip}:{port}...")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Share failed", str(exc))

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
        detail = getattr(state, "detail", "") or getattr(state, "phase", "")
        frames = getattr(state, "frames", 0)
        phase = getattr(state, "phase", "")
        self._status.setText(f"[{phase}] {detail} (frames={frames})")

    def _on_session_finished(self, _state: Any) -> None:
        self._share_btn.setEnabled(True)
        self._stop_share_btn.setEnabled(False)
        self._preview_btn.setEnabled(True)
        if not self._status.text().startswith("["):
            self._status.setText("Share stopped.")

    def _on_session_failed(self, message: str) -> None:
        self._share_btn.setEnabled(True)
        self._stop_share_btn.setEnabled(False)
        self._preview_btn.setEnabled(True)
        self._status.setText(message)
        QMessageBox.critical(self, "Share failed", message)
