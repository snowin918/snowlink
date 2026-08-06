"""Persist Experiment E JSON result files."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from snowlink.rtc.models import ExperimentEResult

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename_component(value: str, *, max_len: int = 64) -> str:
    cleaned = value.strip().replace("..", ".")
    cleaned = _UNSAFE_FILENAME.sub("-", cleaned).strip("-._")
    cleaned = cleaned.replace("..", ".")
    if not cleaned:
        cleaned = "unnamed"
    return cleaned[:max_len]


def result_filename(
    *,
    role: str,
    session_name: str,
    when: datetime | None = None,
) -> str:
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%S")
    parts = [
        stamp,
        sanitize_filename_component(role),
        sanitize_filename_component(session_name),
    ]
    return "_".join(parts) + ".json"


def write_result(
    result: ExperimentEResult,
    results_dir: Path,
    *,
    filename: str | None = None,
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    name = filename or result_filename(
        role=result.role,
        session_name=result.session_name or "unnamed",
    )
    safe_name = Path(name).name
    path = results_dir / safe_name
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_result(path: Path) -> ExperimentEResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Result file is not a JSON object: {path}")
    return ExperimentEResult.from_dict(data)
