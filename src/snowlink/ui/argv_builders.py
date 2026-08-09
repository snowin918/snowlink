"""Pure argv builders for Phase 0 experiment scripts (no Qt / no hardware)."""

from __future__ import annotations

from typing import Literal

ExperimentId = Literal["a", "b", "c", "d", "e", "f"]

SESSION_NAMES = ("vpn-on-on",)
BACKENDS = ("dxgi", "winrt")
PRESETS = ("low", "balanced", "high")
PRESET_LABELS: dict[str, str] = {
    "low": "Lower quality",
    "balanced": "Balanced",
    "high": "Higher quality (experimental)",
}
MACHINE_LABELS = ("computer-a", "computer-b")


def populate_preset_combo(combo: object, *, current: str = "low") -> None:
    """Fill a QComboBox with preset keys in userData and labeled display text."""
    clear = getattr(combo, "clear", None)
    add_item = getattr(combo, "addItem", None)
    find_data = getattr(combo, "findData", None)
    set_index = getattr(combo, "setCurrentIndex", None)
    if clear is None or add_item is None:
        return
    clear()
    for key in PRESETS:
        add_item(PRESET_LABELS.get(key, key), key)
    if find_data is not None and set_index is not None:
        idx = find_data(current if current in PRESETS else "low")
        if idx >= 0:
            set_index(idx)


def preset_from_combo(combo: object, *, default: str = "low") -> str:
    """Read the preset key from a combo populated by ``populate_preset_combo``."""
    data = getattr(combo, "currentData", lambda: None)()
    if isinstance(data, str) and data in PRESETS:
        return data
    text = str(getattr(combo, "currentText", lambda: default)() or default).strip().lower()
    if text in PRESETS:
        return text
    for key, label in PRESET_LABELS.items():
        if text == label.lower():
            return key
    return default if default in PRESETS else "low"


def build_experiment_a_argv(
    action: Literal["list", "serve", "connect"],
    *,
    ip: str = "",
    port: int = 3847,
    message: str = "snowlink-test",
    timeout: float = 5.0,
    serve_forever: bool = False,
    as_json: bool = False,
) -> list[str]:
    args: list[str] = [action]
    if as_json:
        args.append("--json")
    if action == "serve":
        if not ip.strip():
            raise ValueError("Experiment A serve requires --ip")
        args.extend(["--ip", ip.strip(), "--port", str(port)])
        if serve_forever:
            args.append("--serve-forever")
    elif action == "connect":
        if not ip.strip():
            raise ValueError("Experiment A connect requires --ip")
        args.extend(
            [
                "--ip",
                ip.strip(),
                "--port",
                str(port),
                "--message",
                message,
                "--timeout",
                str(timeout),
            ]
        )
    return args


def build_experiment_b_argv(
    action: Literal["guide", "serve", "connect", "summarize"],
    *,
    ip: str = "",
    source_ip: str = "",
    port: int = 3847,
    session_name: str = "vpn-off-off",
    timeout: float = 5.0,
    serve_forever: bool = True,
    as_json: bool = False,
    results_dir: str = "",
) -> list[str]:
    args: list[str] = [action]
    if as_json and action != "guide":
        args.append("--json")
    if results_dir.strip() and action != "guide":
        args.extend(["--results-dir", results_dir.strip()])
    if action == "serve":
        if not ip.strip():
            raise ValueError("Experiment B serve requires --ip")
        args.extend(
            [
                "--ip",
                ip.strip(),
                "--port",
                str(port),
                "--session-name",
                session_name.strip(),
            ]
        )
        if serve_forever:
            args.append("--serve-forever")
    elif action == "connect":
        if not ip.strip():
            raise ValueError("Experiment B connect requires --ip")
        args.extend(
            [
                "--ip",
                ip.strip(),
                "--port",
                str(port),
                "--session-name",
                session_name.strip(),
                "--timeout",
                str(timeout),
            ]
        )
        if source_ip.strip():
            args.extend(["--source-ip", source_ip.strip()])
    return args


def build_experiment_c_argv(
    action: Literal["list", "preview", "benchmark", "suite"],
    *,
    monitor: int = 0,
    backend: str = "dxgi",
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
    duration: int = 60,
    machine_label: str = "",
    preset: str = "",
    no_preview: bool = True,
    as_json: bool = False,
    results_dir: str = "",
) -> list[str]:
    args: list[str] = [action]
    if action == "list":
        if as_json:
            args.append("--json")
        return args

    args.extend(
        [
            "--monitor",
            str(monitor),
            "--backend",
            backend.strip().lower() or "dxgi",
        ]
    )
    if action == "suite":
        args.extend(["--duration-per-preset", str(duration)])
        if machine_label.strip():
            args.extend(["--machine-label", machine_label.strip()])
        if as_json:
            args.append("--json")
        if results_dir.strip():
            args.extend(["--results-dir", results_dir.strip()])
        return args

    if preset.strip():
        args.extend(["--preset", preset.strip().lower()])
    else:
        args.extend(
            [
                "--fps",
                str(fps),
                "--width",
                str(width),
                "--height",
                str(height),
            ]
        )
    args.extend(["--duration", str(duration)])
    if machine_label.strip():
        args.extend(["--machine-label", machine_label.strip()])
    if as_json:
        args.append("--json")
    if results_dir.strip():
        args.extend(["--results-dir", results_dir.strip()])
    if action == "benchmark" and no_preview:
        args.append("--no-preview")
    return args


def build_experiment_d_argv(
    action: Literal["list", "benchmark"],
    *,
    duration: int = 60,
    as_json: bool = False,
    results_dir: str = "",
    muted: bool = False,
) -> list[str]:
    args: list[str] = [action]
    if action == "list":
        if as_json:
            args.append("--json")
        return args
    args.extend(["--duration", str(duration)])
    if muted:
        args.append("--muted")
    if as_json:
        args.append("--json")
    if results_dir.strip():
        args.extend(["--results-dir", results_dir.strip()])
    return args


def build_experiment_e_argv(
    action: Literal["guide", "send", "receive"],
    *,
    bind_ip: str = "",
    remote_ip: str = "",
    source_ip: str = "",
    port: int = 3847,
    duration: float = 120.0,
    session_name: str = "unnamed",
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    no_preview: bool = False,
    as_json: bool = False,
    results_dir: str = "",
) -> list[str]:
    args: list[str] = [action]
    if action == "guide":
        return args
    args.extend(
        [
            "--port",
            str(port),
            "--fps",
            str(fps),
            "--width",
            str(width),
            "--height",
            str(height),
            "--duration",
            str(duration),
            "--session-name",
            session_name.strip() or "unnamed",
        ]
    )
    if as_json:
        args.append("--json")
    if results_dir.strip():
        args.extend(["--results-dir", results_dir.strip()])
    if action == "send":
        if not bind_ip.strip():
            raise ValueError("Experiment E send requires --bind-ip")
        args.extend(["--bind-ip", bind_ip.strip()])
    else:
        if not remote_ip.strip():
            raise ValueError("Experiment E receive requires --remote-ip")
        args.extend(["--remote-ip", remote_ip.strip()])
        if source_ip.strip():
            args.extend(["--source-ip", source_ip.strip()])
        if no_preview:
            args.append("--no-preview")
    return args


def build_experiment_f_argv(
    action: Literal["guide", "send", "receive"],
    *,
    bind_ip: str = "",
    remote_ip: str = "",
    source_ip: str = "",
    port: int = 3849,
    duration: float = 120.0,
    session_name: str = "unnamed",
    no_playback: bool = False,
    as_json: bool = False,
    results_dir: str = "",
) -> list[str]:
    args: list[str] = [action]
    if action == "guide":
        return args
    args.extend(
        [
            "--port",
            str(port),
            "--duration",
            str(duration),
            "--session-name",
            session_name.strip() or "unnamed",
        ]
    )
    if as_json:
        args.append("--json")
    if results_dir.strip():
        args.extend(["--results-dir", results_dir.strip()])
    if action == "send":
        if not bind_ip.strip():
            raise ValueError("Experiment F send requires --bind-ip")
        args.extend(["--bind-ip", bind_ip.strip()])
    else:
        if not remote_ip.strip():
            raise ValueError("Experiment F receive requires --remote-ip")
        args.extend(["--remote-ip", remote_ip.strip()])
        if source_ip.strip():
            args.extend(["--source-ip", source_ip.strip()])
        if no_playback:
            args.append("--no-playback")
    return args


SCRIPT_NAMES: dict[ExperimentId, str] = {
    "a": "experiment_a_adapter_bind.py",
    "b": "experiment_b_two_machine_tcp.py",
    "c": "experiment_c_screen_capture.py",
    "d": "experiment_d_audio_loopback.py",
    "e": "experiment_e_webrtc_video.py",
    "f": "experiment_f_webrtc_audio.py",
}
