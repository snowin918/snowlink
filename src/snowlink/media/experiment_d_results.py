"""Persist Experiment D JSON result files."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from snowlink.media.audio_models import ExperimentDResult

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
    capture_label: str,
    sample_rate: int,
    channels: int,
    when: datetime | None = None,
) -> str:
    """Build a sanitized Experiment D result filename."""
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%S")
    ch_label = "stereo" if channels >= 2 else "mono"
    rate_label = f"{sample_rate // 1000}k" if sample_rate % 1000 == 0 else f"{sample_rate}hz"
    parts = [
        stamp,
        f"loopback-{sanitize_filename_component(capture_label)}",
        rate_label,
        ch_label,
    ]
    return "_".join(parts) + ".json"


def write_result(
    result: ExperimentDResult,
    results_dir: Path,
    *,
    filename: str | None = None,
) -> Path:
    """Write *result* as JSON under *results_dir*; return the file path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    cfg = result.configuration
    if filename:
        name = filename
    elif cfg is not None:
        name = result_filename(
            capture_label=cfg.capture_device,
            sample_rate=cfg.target_sample_rate,
            channels=cfg.target_channels,
        )
    else:
        name = result_filename(capture_label="unknown", sample_rate=48000, channels=2)
    safe_name = Path(name).name
    path = results_dir / safe_name
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_result(path: Path) -> ExperimentDResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Result file is not a JSON object: {path}")
    return ExperimentDResult.from_dict(data)
