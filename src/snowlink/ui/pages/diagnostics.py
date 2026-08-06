"""Diagnostics page — Phase 0 Experiments A–F runner."""

from __future__ import annotations

from collections.abc import Callable

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

from snowlink.ui import argv_builders as ab
from snowlink.ui.paths import app_workdir, experiment_script, results_dir
from snowlink.ui.workers import ExperimentProcessRunner


class DiagnosticsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._runner = ExperimentProcessRunner(self)
        self._runner.output.connect(self._append_log)
        self._runner.finished.connect(self._on_finished)
        self._runner.started.connect(self._on_started)
        self._builders: dict[str, Callable[[], tuple[str, list[str]]]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("Diagnostics / Phase 0 Tests")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Runs the real experiment scripts under experiments/ via the project "
            "Python interpreter. Results stay under experiment-results/ (gitignored)."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

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
        self._log.setMinimumHeight(200)
        layout.addWidget(self._log, 2)
        clear.clicked.connect(self._log.clear)

        self._status = QLabel("Idle.")
        self._status.setObjectName("hint")
        layout.addWidget(self._status)

    def _append_log(self, text: str) -> None:
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)

    def _on_started(self, command: str) -> None:
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status.setText("Running…")
        self._append_log(f"\n$ {command}\n")

    def _on_finished(self, code: int) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status.setText(f"Finished with exit code {code}.")
        self._append_log(f"\n[exit {code}]\n")

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
        port.setValue(3848)
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
