"""Unit tests for Phase 0 diagnostics argv builders (no hardware / no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from snowlink.ui.argv_builders import (
    PRESET_LABELS,
    build_experiment_a_argv,
    build_experiment_b_argv,
    build_experiment_c_argv,
    build_experiment_d_argv,
    build_experiment_e_argv,
    build_experiment_f_argv,
    populate_preset_combo,
    preset_from_combo,
)


def test_experiment_a_list_and_serve() -> None:
    assert build_experiment_a_argv("list") == ["list"]
    assert build_experiment_a_argv("list", as_json=True) == ["list", "--json"]
    serve = build_experiment_a_argv(
        "serve",
        ip="192.168.1.25",
        port=3847,
        serve_forever=True,
    )
    assert serve == [
        "serve",
        "--ip",
        "192.168.1.25",
        "--port",
        "3847",
        "--serve-forever",
    ]


def test_experiment_a_serve_requires_ip() -> None:
    with pytest.raises(ValueError, match="require"):
        build_experiment_a_argv("serve", ip="")


def test_experiment_b_connect_session() -> None:
    args = build_experiment_b_argv(
        "connect",
        ip="192.168.1.25",
        source_ip="192.168.1.30",
        session_name="vpn-on-on",
        results_dir="experiment-results/experiment-b",
    )
    assert args[:1] == ["connect"]
    assert "--session-name" in args
    assert "vpn-on-on" in args
    assert "--source-ip" in args
    assert "192.168.1.30" in args


def test_experiment_c_balanced_benchmark() -> None:
    args = build_experiment_c_argv(
        "benchmark",
        monitor=0,
        backend="dxgi",
        duration=60,
        machine_label="computer-a",
        preset="balanced",
        no_preview=True,
        as_json=True,
        results_dir="experiment-results/experiment-c",
    )
    assert args[0] == "benchmark"
    assert "--preset" in args and "balanced" in args
    assert "--machine-label" in args and "computer-a" in args
    assert "--no-preview" in args
    assert "--duration" in args and "60" in args
    assert "--fps" not in args


def test_experiment_c_list_only() -> None:
    assert build_experiment_c_argv("list", as_json=True) == ["list", "--json"]


def test_experiment_d_benchmark() -> None:
    args = build_experiment_d_argv(
        "benchmark",
        duration=60,
        muted=True,
        as_json=True,
        results_dir="experiment-results/experiment-d",
    )
    assert args[0] == "benchmark"
    assert "--muted" in args
    assert "--duration" in args


def test_experiment_e_send_requires_bind() -> None:
    with pytest.raises(ValueError, match="bind-ip"):
        build_experiment_e_argv("send", bind_ip="")
    args = build_experiment_e_argv(
        "send",
        bind_ip="192.168.1.25",
        session_name="lab",
        as_json=True,
    )
    assert "--bind-ip" in args
    assert "192.168.1.25" in args


def test_experiment_f_receive() -> None:
    args = build_experiment_f_argv(
        "receive",
        remote_ip="192.168.1.25",
        source_ip="192.168.1.30",
        no_playback=True,
        as_json=True,
    )
    assert args[0] == "receive"
    assert "--remote-ip" in args
    assert "--no-playback" in args


def test_experiment_process_argv_dev_mode(tmp_path: Path) -> None:
    from snowlink.ui.paths import experiment_process_argv, is_frozen

    script = tmp_path / "experiment_c_screen_capture.py"
    script.write_text("# stub\n", encoding="utf-8")
    program, args = experiment_process_argv(script, ["list", "--json"])
    assert not is_frozen()
    assert args[0] == str(script)
    assert args[1:] == ["list", "--json"]
    assert program  # sys.executable


def test_preset_labels_mark_high_experimental() -> None:
    assert PRESET_LABELS["high"] == "Higher quality (experimental)"
    assert PRESET_LABELS["low"] == "Lower quality"
    assert PRESET_LABELS["balanced"] == "Balanced"


def test_populate_and_read_preset_combo() -> None:
    class FakeCombo:
        def __init__(self) -> None:
            self.items: list[tuple[str, str]] = []
            self._index = -1

        def clear(self) -> None:
            self.items.clear()
            self._index = -1

        def addItem(self, text: str, data: object = None) -> None:  # noqa: N802
            self.items.append((text, str(data)))

        def findData(self, data: object) -> int:  # noqa: N802
            needle = str(data)
            for i, (_t, d) in enumerate(self.items):
                if d == needle:
                    return i
            return -1

        def setCurrentIndex(self, index: int) -> None:  # noqa: N802
            self._index = index

        def currentData(self) -> str | None:  # noqa: N802
            if 0 <= self._index < len(self.items):
                return self.items[self._index][1]
            return None

        def currentText(self) -> str:  # noqa: N802
            if 0 <= self._index < len(self.items):
                return self.items[self._index][0]
            return ""

    combo = FakeCombo()
    populate_preset_combo(combo, current="high")
    assert preset_from_combo(combo) == "high"
    assert combo.currentText() == "Higher quality (experimental)"
    populate_preset_combo(combo, current="balanced")
    assert preset_from_combo(combo) == "balanced"


def test_experiment_e_default_port_is_product_port() -> None:
    args = build_experiment_e_argv("send", bind_ip="192.168.1.25")
    assert "--port" in args
    assert args[args.index("--port") + 1] == "3847"
