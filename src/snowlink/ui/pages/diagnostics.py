"""Diagnostics page — product connectivity checklist + Phase 0 lab runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from snowlink.constants import DEFAULT_SIGNALING_PORT
from snowlink.ui import argv_builders as ab
from snowlink.ui.paths import app_workdir, experiment_script, results_dir
from snowlink.ui.workers import ExperimentProcessRunner


class _ChecklistWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        selected_ip: str,
        port: int,
        remote_ip: str | None,
        skip_handshake: bool,
        live: Any | None,
    ) -> None:
        super().__init__()
        self._selected_ip = selected_ip
        self._port = port
        self._remote_ip = remote_ip
        self._skip_handshake = skip_handshake
        self._live = live

    def run(self) -> None:
        try:
            from snowlink.diagnostics.workflow import run_connectivity_checklist

            report = run_connectivity_checklist(
                selected_ip=self._selected_ip,
                port=self._port,
                remote_ip=self._remote_ip,
                live=self._live,
                skip_handshake=self._skip_handshake,
            )
            self.finished.emit(report)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DiagnosticsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._runner = ExperimentProcessRunner(self)
        self._runner.output.connect(self._append_lab_log)
        self._runner.finished.connect(self._on_lab_finished)
        self._runner.started.connect(self._on_lab_started)
        self._builders: dict[str, Callable[[], tuple[str, list[str]]]] = {}
        self._live_snapshot: Any | None = None
        self._checklist_thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Diagnostics")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Checks whether this PC can listen on the selected address and talk to "
            "the other PC. Use this if Share/View cannot connect."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._show_lab = QCheckBox("Show lab tools")
        self._show_lab.setChecked(False)
        self._show_lab.toggled.connect(self._on_show_lab_toggled)
        layout.addWidget(self._show_lab)

        self._outer = QTabWidget()
        self._outer.addTab(self._build_product_tab(), "Connectivity")
        self._lab_widget = self._build_lab_tabs()
        layout.addWidget(self._outer, 1)

    def set_live_session_snapshot(self, snapshot: Any | None) -> None:
        """Optional Share/View snapshot for ICE / media checklist steps."""
        self._live_snapshot = snapshot

    def _on_show_lab_toggled(self, checked: bool) -> None:
        idx = self._outer.indexOf(self._lab_widget)
        if checked:
            if idx < 0:
                self._outer.addTab(self._lab_widget, "Lab (Phase 0)")
                self._outer.setCurrentWidget(self._lab_widget)
        elif idx >= 0:
            self._outer.removeTab(idx)

    def _build_product_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()

        self._adapter = QComboBox()
        self._adapter.setMinimumWidth(360)
        form.addRow("Network adapter", self._adapter)

        self._diag_port = QSpinBox()
        self._diag_port.setRange(1, 65535)
        self._diag_port.setValue(DEFAULT_SIGNALING_PORT)
        form.addRow("Signaling port", self._diag_port)

        self._remote_ip = QLineEdit()
        self._remote_ip.setPlaceholderText("optional — remote sharer IP for handshake")
        form.addRow("Remote IP", self._remote_ip)

        self._skip_handshake = QCheckBox("Skip signaling handshake probe")
        form.addRow("", self._skip_handshake)
        layout.addLayout(form)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh adapters")
        refresh.clicked.connect(self._refresh_adapters)
        row.addWidget(refresh)

        self._run_checklist_btn = QPushButton("Run connectivity checklist")
        self._run_checklist_btn.setObjectName("primaryButton")
        self._run_checklist_btn.clicked.connect(self._run_checklist)
        row.addWidget(self._run_checklist_btn)

        refresh_logs = QPushButton("Refresh log tail")
        refresh_logs.clicked.connect(self._refresh_log_tail)
        row.addWidget(refresh_logs)
        row.addStretch(1)
        layout.addLayout(row)

        self._product_log = QPlainTextEdit()
        self._product_log.setObjectName("logView")
        self._product_log.setReadOnly(True)
        layout.addWidget(self._product_log, 1)

        log_label = QLabel("Recent sanitized log entries")
        log_label.setObjectName("hint")
        layout.addWidget(log_label)

        self._log_tail = QPlainTextEdit()
        self._log_tail.setObjectName("logView")
        self._log_tail.setReadOnly(True)
        self._log_tail.setMaximumHeight(160)
        layout.addWidget(self._log_tail)

        self._product_status = QLabel("Idle.")
        self._product_status.setObjectName("hint")
        layout.addWidget(self._product_status)

        self._refresh_adapters()
        self._refresh_log_tail()
        return w

    def _build_lab_tabs(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_tab_a(), "A Adapters")
        self._tabs.addTab(self._build_tab_b(), "B TCP/VPN")
        self._tabs.addTab(self._build_tab_c(), "C Capture")
        self._tabs.addTab(self._build_tab_d(), "D Audio")
        self._tabs.addTab(self._build_tab_e(), "E WebRTC V")
        self._tabs.addTab(self._build_tab_f(), "F WebRTC A")
        layout.addWidget(self._tabs, 1)

        controls = QHBoxLayout()
        self._run_btn = QPushButton("Run selected")
        self._run_btn.setObjectName("primaryButton")
        self._run_btn.clicked.connect(self._run_selected)
        controls.addWidget(self._run_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._runner.stop)
        controls.addWidget(self._stop_btn)

        open_results = QPushButton("Open results folder")
        open_results.clicked.connect(self._open_results)
        controls.addWidget(open_results)

        clear = QPushButton("Clear log")
        controls.addWidget(clear)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._log = QPlainTextEdit()
        self._log.setObjectName("logView")
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(160)
        layout.addWidget(self._log, 2)
        clear.clicked.connect(self._log.clear)

        self._status = QLabel("Idle.")
        self._status.setObjectName("hint")
        layout.addWidget(self._status)
        return outer

    def _refresh_adapters(self) -> None:
        self._adapter.clear()
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
                # Prefer physical LAN by default.
                try:
                    from snowlink.net.adapter_selection import select_preferred_endpoint

                    selected = select_preferred_endpoint(adapters)
                    if selected is not None:
                        for i in range(self._adapter.count()):
                            item = self._adapter.itemData(i)
                            if (
                                item is not None
                                and getattr(item, "adapter_id", None)
                                == selected.adapter.adapter_id
                            ):
                                self._adapter.setCurrentIndex(i)
                                break
                except Exception:
                    pass
            else:
                self._adapter.addItem("(adapter list requires Windows)", None)
        except Exception as exc:  # noqa: BLE001
            self._adapter.addItem(f"(adapter error: {exc})", None)

    def _refresh_log_tail(self) -> None:
        try:
            from snowlink.logging_setup import log_file_path, read_recent_log_lines

            lines = read_recent_log_lines(80)
            if not lines:
                path = log_file_path()
                self._log_tail.setPlainText(f"(no log entries yet — {path})")
            else:
                self._log_tail.setPlainText("\n".join(lines))
                # Keep latest lines visible.
                cursor = self._log_tail.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self._log_tail.setTextCursor(cursor)
        except Exception as exc:  # noqa: BLE001
            self._log_tail.setPlainText(f"(log tail unavailable: {exc})")

    def _selected_bind_ip(self) -> str | None:
        adapter = self._adapter.currentData()
        if adapter is None:
            return None
        addrs = getattr(adapter, "ipv4_addresses", None) or []
        if not addrs:
            return None
        return str(addrs[0].address)

    def _run_checklist(self) -> None:
        if self._checklist_thread is not None and self._checklist_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Checklist is already running.")
            return
        bind_ip = self._selected_bind_ip()
        if not bind_ip:
            QMessageBox.warning(self, "No IP", "Select an adapter with an IPv4 address.")
            return
        remote = self._remote_ip.text().strip() or None
        port = int(self._diag_port.value())
        self._run_checklist_btn.setEnabled(False)
        self._product_status.setText("Running checklist…")
        self._product_log.clear()
        self._product_log.appendPlainText(f"Selected {bind_ip}:{port}…\n")

        thread = QThread(self)
        worker = _ChecklistWorker(
            selected_ip=bind_ip,
            port=port,
            remote_ip=remote,
            skip_handshake=self._skip_handshake.isChecked(),
            live=self._live_snapshot,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_checklist_finished)
        worker.failed.connect(self._on_checklist_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._checklist_thread = thread
        thread.start()

    def _on_checklist_finished(self, report: Any) -> None:
        self._run_checklist_btn.setEnabled(True)
        text = report.format_text() if hasattr(report, "format_text") else str(report)
        self._product_log.setPlainText(text)
        overall = getattr(report, "overall", "?")
        self._product_status.setText(f"Checklist finished — overall {overall}.")
        self._refresh_log_tail()

    def _on_checklist_failed(self, message: str) -> None:
        self._run_checklist_btn.setEnabled(True)
        self._product_status.setText(message)
        self._product_log.appendPlainText(message)
        QMessageBox.critical(self, "Checklist failed", message)

    def _append_lab_log(self, text: str) -> None:
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)

    def _on_lab_started(self, command: str) -> None:
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status.setText("Running…")
        self._append_lab_log(f"\n$ {command}\n")

    def _on_lab_finished(self, code: int) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status.setText(f"Finished with exit code {code}.")
        self._append_lab_log(f"\n[exit {code}]\n")

    def _open_results(self) -> None:
        letter = "abcdef"[self._tabs.currentIndex()]
        path = results_dir(letter)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def _run_selected(self) -> None:
        if self._runner.is_running:
            QMessageBox.warning(self, "Busy", "Stop the current run first.")
            return
        letter = "abcdef"[self._tabs.currentIndex()]
        builder = self._builders.get(letter)
        if builder is None:
            return
        try:
            script_name, argv = builder()
            script = experiment_script(script_name)
            self._runner.start(script, argv, working_directory=app_workdir())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Cannot run", str(exc))

    def _build_tab_a(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["list", "serve", "connect"])
        form.addRow("Action", action)
        ip = QLineEdit()
        ip.setPlaceholderText("192.168.1.25")
        form.addRow("IP", ip)
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(3847)
        form.addRow("Port", port)
        forever = QCheckBox("serve-forever")
        form.addRow("", forever)
        as_json = QCheckBox("JSON stdout")
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            act = action.currentText()
            return ab.SCRIPT_NAMES["a"], ab.build_experiment_a_argv(
                act,  # type: ignore[arg-type]
                ip=ip.text(),
                port=port.value(),
                serve_forever=forever.isChecked(),
                as_json=as_json.isChecked(),
            )

        self._builders["a"] = build
        return w

    def _build_tab_b(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["guide", "serve", "connect", "summarize"])
        form.addRow("Action", action)
        ip = QLineEdit()
        form.addRow("IP (A LAN / remote)", ip)
        source = QLineEdit()
        form.addRow("Source IP (client)", source)
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(3847)
        form.addRow("Port", port)
        session = QComboBox()
        session.addItems(list(ab.SESSION_NAMES))
        form.addRow("Session name", session)
        forever = QCheckBox("serve-forever")
        forever.setChecked(True)
        form.addRow("", forever)
        as_json = QCheckBox("JSON")
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            return ab.SCRIPT_NAMES["b"], ab.build_experiment_b_argv(
                action.currentText(),  # type: ignore[arg-type]
                ip=ip.text(),
                source_ip=source.text(),
                port=port.value(),
                session_name=session.currentText(),
                serve_forever=forever.isChecked(),
                as_json=as_json.isChecked(),
                results_dir=str(results_dir("b")),
            )

        self._builders["b"] = build
        return w

    def _build_tab_c(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["list", "preview", "benchmark", "suite"])
        action.setCurrentText("benchmark")
        form.addRow("Action", action)
        monitor = QSpinBox()
        monitor.setRange(0, 15)
        form.addRow("Monitor", monitor)
        backend = QComboBox()
        backend.addItems(list(ab.BACKENDS))
        form.addRow("Backend", backend)
        duration = QSpinBox()
        duration.setRange(1, 3600)
        duration.setValue(60)
        form.addRow("Duration (s)", duration)
        label = QComboBox()
        label.setEditable(True)
        label.addItems(["", *ab.MACHINE_LABELS])
        form.addRow("Machine label", label)
        preset = QComboBox()
        preset.addItems(["", *ab.PRESETS])
        preset.setCurrentText("balanced")
        form.addRow("Preset", preset)
        no_preview = QCheckBox("no-preview (benchmark)")
        no_preview.setChecked(True)
        form.addRow("", no_preview)
        as_json = QCheckBox("JSON")
        as_json.setChecked(True)
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            return ab.SCRIPT_NAMES["c"], ab.build_experiment_c_argv(
                action.currentText(),  # type: ignore[arg-type]
                monitor=monitor.value(),
                backend=backend.currentText(),
                duration=duration.value(),
                machine_label=label.currentText().strip(),
                preset=preset.currentText().strip(),
                no_preview=no_preview.isChecked(),
                as_json=as_json.isChecked(),
                results_dir=str(results_dir("c")),
            )

        self._builders["c"] = build
        return w

    def _build_tab_d(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["list", "benchmark"])
        form.addRow("Action", action)
        duration = QSpinBox()
        duration.setRange(1, 3600)
        duration.setValue(60)
        form.addRow("Duration (s)", duration)
        muted = QCheckBox("muted")
        form.addRow("", muted)
        as_json = QCheckBox("JSON")
        as_json.setChecked(True)
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            return ab.SCRIPT_NAMES["d"], ab.build_experiment_d_argv(
                action.currentText(),  # type: ignore[arg-type]
                duration=duration.value(),
                muted=muted.isChecked(),
                as_json=as_json.isChecked(),
                results_dir=str(results_dir("d")),
            )

        self._builders["d"] = build
        return w

    def _build_tab_e(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["guide", "send", "receive"])
        form.addRow("Action", action)
        bind_ip = QLineEdit()
        form.addRow("Bind IP (send)", bind_ip)
        remote_ip = QLineEdit()
        form.addRow("Remote IP (receive)", remote_ip)
        source_ip = QLineEdit()
        form.addRow("Source IP (receive)", source_ip)
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(3847)
        form.addRow("Port", port)
        duration = QDoubleSpinBox()
        duration.setRange(1.0, 3600.0)
        duration.setValue(120.0)
        form.addRow("Duration (s)", duration)
        session = QLineEdit("unnamed")
        form.addRow("Session name", session)
        no_preview = QCheckBox("no-preview (receive)")
        form.addRow("", no_preview)
        as_json = QCheckBox("JSON")
        as_json.setChecked(True)
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            return ab.SCRIPT_NAMES["e"], ab.build_experiment_e_argv(
                action.currentText(),  # type: ignore[arg-type]
                bind_ip=bind_ip.text(),
                remote_ip=remote_ip.text(),
                source_ip=source_ip.text(),
                port=port.value(),
                duration=float(duration.value()),
                session_name=session.text(),
                no_preview=no_preview.isChecked(),
                as_json=as_json.isChecked(),
                results_dir=str(results_dir("e")),
            )

        self._builders["e"] = build
        return w

    def _build_tab_f(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        action = QComboBox()
        action.addItems(["guide", "send", "receive"])
        form.addRow("Action", action)
        bind_ip = QLineEdit()
        form.addRow("Bind IP (send)", bind_ip)
        remote_ip = QLineEdit()
        form.addRow("Remote IP (receive)", remote_ip)
        source_ip = QLineEdit()
        form.addRow("Source IP (receive)", source_ip)
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(3849)
        form.addRow("Port", port)
        duration = QDoubleSpinBox()
        duration.setRange(1.0, 3600.0)
        duration.setValue(120.0)
        form.addRow("Duration (s)", duration)
        session = QLineEdit("unnamed")
        form.addRow("Session name", session)
        no_playback = QCheckBox("no-playback (receive)")
        form.addRow("", no_playback)
        as_json = QCheckBox("JSON")
        as_json.setChecked(True)
        form.addRow("", as_json)

        def build() -> tuple[str, list[str]]:
            return ab.SCRIPT_NAMES["f"], ab.build_experiment_f_argv(
                action.currentText(),  # type: ignore[arg-type]
                bind_ip=bind_ip.text(),
                remote_ip=remote_ip.text(),
                source_ip=source_ip.text(),
                port=port.value(),
                duration=float(duration.value()),
                session_name=session.text(),
                no_playback=no_playback.isChecked(),
                as_json=as_json.isChecked(),
                results_dir=str(results_dir("f")),
            )

        self._builders["f"] = build
        return w
