"""Persist and summarize Experiment B JSON result files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from snowlink.net.experiment_b_models import (
    SCHEMA_VERSION,
    ExperimentBResult,
)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class SchemaVersionError(ValueError):
    """Raised when result files mix incompatible schema versions."""


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
    role: str,
    session_name: str,
    when: datetime | None = None,
    test_id: str | None = None,
) -> str:
    """Build a sanitized result filename."""
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%S")
    parts = [
        stamp,
        sanitize_filename_component(session_name),
        sanitize_filename_component(role),
    ]
    if test_id:
        parts.append(sanitize_filename_component(test_id, max_len=16))
    return "_".join(parts) + ".json"


def write_result(
    result: ExperimentBResult,
    results_dir: Path,
    *,
    filename: str | None = None,
) -> Path:
    """Write *result* as JSON under *results_dir*; return the file path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    name = filename or result_filename(
        role=result.role,
        session_name=result.session_name or "session",
        test_id=result.test_id or None,
    )
    # Prevent directory traversal even if callers pass a custom name.
    safe_name = Path(name).name
    path = results_dir / safe_name
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_result(path: Path) -> ExperimentBResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Result file is not a JSON object: {path}")
    return ExperimentBResult.from_dict(data)


@dataclass(frozen=True, slots=True)
class SummaryRow:
    session_name: str
    success: bool
    connect_display: str
    source_ip: str
    destination: str
    path: str


def load_client_results(
    results_dir: Path,
    *,
    expected_schema_version: int = SCHEMA_VERSION,
) -> list[tuple[Path, ExperimentBResult]]:
    """Load client-role results; reject incompatible schema versions."""
    if not results_dir.is_dir():
        return []
    loaded: list[tuple[Path, ExperimentBResult]] = []
    versions: set[int] = set()
    for path in sorted(results_dir.glob("*.json")):
        try:
            result = load_result(path)
        except (OSError, ValueError, json.JSONDecodeError, TypeError, KeyError):
            continue
        if result.role != "client":
            continue
        versions.add(result.schema_version)
        loaded.append((path, result))

    if not loaded:
        return []
    if len(versions) > 1:
        raise SchemaVersionError(
            f"Incompatible schema versions in {results_dir}: {sorted(versions)}"
        )
    only = next(iter(versions))
    if only != expected_schema_version:
        raise SchemaVersionError(
            f"Result schema_version {only} is incompatible with expected "
            f"{expected_schema_version}"
        )
    return loaded


def summarize_results(
    results_dir: Path,
    *,
    expected_schema_version: int = SCHEMA_VERSION,
) -> list[SummaryRow]:
    """Build summary rows for client results (latest per session_name wins)."""
    loaded = load_client_results(
        results_dir,
        expected_schema_version=expected_schema_version,
    )
    latest: dict[str, tuple[Path, ExperimentBResult]] = {}
    for path, result in loaded:
        key = result.session_name or path.stem
        prev = latest.get(key)
        if prev is None or path.name >= prev[0].name:
            latest[key] = (path, result)

    rows: list[SummaryRow] = []
    for session in sorted(latest):
        path, result = latest[session]
        connect = result.timing_ms.connect_ms
        if result.success and connect is not None:
            connect_display = f"{connect:.1f}"
        elif result.error and isinstance(result.error, dict):
            connect_display = str(result.error.get("code", "FAIL")).lower().replace("_", " ")
            if connect_display.startswith("connection "):
                connect_display = connect_display.split(" ", 1)[-1]
        else:
            connect_display = "fail"
        source = (
            (result.local.actual_source_ip if result.local else None)
            or (result.local.requested_source_ip if result.local else None)
            or "-"
        )
        if result.remote:
            destination = f"{result.remote.ip}"
        else:
            destination = "-"
        rows.append(
            SummaryRow(
                session_name=session,
                success=result.success,
                connect_display=connect_display,
                source_ip=str(source),
                destination=destination,
                path=str(path),
            )
        )
    return rows


def format_summary_table(rows: list[SummaryRow]) -> str:
    headers = ("Scenario", "Success", "Connect ms", "Source IP", "Destination")
    body: list[tuple[str, str, str, str, str]] = [
        (
            row.session_name,
            "PASS" if row.success else "FAIL",
            row.connect_display,
            row.source_ip,
            row.destination,
        )
        for row in rows
    ]
    widths = [len(h) for h in headers]
    for line in body:
        for i, cell in enumerate(line):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt(headers), fmt(tuple("-" * w for w in widths))]
    lines.extend(fmt(row) for row in body)
    if not body:
        lines.append("(no client result files found)")
    return "\n".join(lines)
