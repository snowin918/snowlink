"""Persist Experiment C JSON result files."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from snowlink.media.capture_models import ExperimentCResult

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename_component(value: str, *, max_len: int = 64) -> str:
    """Make a path component safe for result filenames (no path separators)."""
    cleaned = value.strip().replace("..", ".")
    cleaned = _UNSAFE_FILENAME.sub("-", cleaned).strip("-._")
    cleaned = cleaned.replace("..", ".")
    if not cleaned:
        cleaned = "unnamed"
    return cleaned[:max_len]


def result_filename(
    *,
    monitor: int,
    backend: str,
    preset_or_label: str,
    when: datetime | None = None,
) -> str:
    """Build a sanitized Experiment C result filename."""
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%S")
    parts = [
        stamp,
        f"monitor-{monitor}",
        sanitize_filename_component(backend),
        sanitize_filename_component(preset_or_label),
    ]
    return "_".join(parts) + ".json"


def write_result(
    result: ExperimentCResult,
    results_dir: Path,
    *,
    filename: str | None = None,
) -> Path:
    """Write *result* as JSON under *results_dir*; return the file path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    cfg = result.configuration
    label = "custom"
    if cfg is not None:
        label = cfg.preset_name or f"{cfg.requested_width}x{cfg.requested_height}"
        name = filename or result_filename(
            monitor=cfg.monitor,
            backend=cfg.backend,
            preset_or_label=label,
        )
    else:
        name = filename or result_filename(
            monitor=0,
            backend="unknown",
            preset_or_label=label,
        )
    safe_name = Path(name).name
    path = results_dir / safe_name
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_result(path: Path) -> ExperimentCResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Result file is not a JSON object: {path}")
    return ExperimentCResult.from_dict(data)
