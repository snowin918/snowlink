"""Repository / experiments path helpers for the UI and diagnostics runner."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def package_root() -> Path:
    """Return ``src/snowlink`` (or the frozen equivalent)."""
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    """Best-effort Snowlink repository root (contains ``experiments/``).

    When frozen (PyInstaller onedir), looks next to the executable and under
    ``sys._MEIPASS`` for a bundled ``experiments/`` folder.
    """
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir))
        for candidate in (
            exe_dir,
            meipass,
            exe_dir / "_internal",
            meipass.parent,
        ):
            if (candidate / "experiments").is_dir():
                return candidate
        return exe_dir

    here = Path(__file__).resolve()
    # src/snowlink/ui/paths.py -> parents: ui, snowlink, src, repo
    candidates = [
        here.parents[3],
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "experiments").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    for parent in here.parents:
        if (parent / "experiments").is_dir() and (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def experiments_dir() -> Path:
    return repo_root() / "experiments"


def experiment_script(name: str) -> Path:
    """Return path to ``experiments/<name>.py``."""
    path = experiments_dir() / name
    if not path.suffix:
        path = path.with_suffix(".py")
    return path


def python_executable() -> str:
    return sys.executable


def app_workdir() -> Path:
    """Writable working directory for experiment subprocesses."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return repo_root()


def results_dir(experiment: str) -> Path:
    """Default results directory for experiment letter ``a``…``f``."""
    key = experiment.strip().lower()
    mapping = {
        "a": "experiment-a",
        "b": "experiment-b",
        "c": "experiment-c",
        "d": "experiment-d",
        "e": "experiment-e",
        "f": "experiment-f",
    }
    folder = mapping.get(key, f"experiment-{key}")
    if is_frozen():
        # Writable location next to the exe (not inside read-only _internal).
        base = Path(sys.executable).resolve().parent
        return base / "experiment-results" / folder
    return repo_root() / "experiment-results" / folder


def experiment_process_argv(script: Path, argv: list[str]) -> tuple[str, list[str]]:
    """Return ``(program, args)`` to run an experiment script.

    Dev: ``python experiments/foo.py …``
    Frozen: ``Snowlink.exe --experiment foo …``
    """
    program = python_executable()
    if is_frozen():
        return program, ["--experiment", script.stem, *argv]
    return program, [str(script), *argv]
