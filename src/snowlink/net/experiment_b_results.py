"""Persist and summarize Experiment B JSON result files."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from snowlink.net.experiment_b_models import (
    KNOWN_SESSION_NAMES,
    REQUIRED_SESSION_NAMES,
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


class EvidenceStatus(StrEnum):
    """Status of one required Experiment B scenario against archived client JSON."""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    session_name: str
    status: EvidenceStatus
    path: str | None
    detail: str
    success: bool | None = None
    source_ip: str | None = None
    destination_ip: str | None = None


def is_loopback_ipv4(address: str | None) -> bool:
    """Return True when *address* is IPv4 loopback (not valid two-computer evidence)."""
    if address is None or not str(address).strip():
        return False
    try:
        return bool(ipaddress.IPv4Address(str(address).strip()).is_loopback)
    except ValueError:
        return False


def _client_ips_are_loopback(result: ExperimentBResult) -> bool:
    remote_ip = result.remote.ip if result.remote else None
    source_ip = None
    if result.local is not None:
        source_ip = result.local.actual_source_ip or result.local.requested_source_ip
    return is_loopback_ipv4(remote_ip) or is_loopback_ipv4(source_ip)


@dataclass(frozen=True, slots=True)
class _ClientFileRef:
    path: Path
    result: ExperimentBResult | None
    load_error: str | None = None


def _session_hint_from_name(path: Path) -> str | None:
    stem = path.stem
    padded = f"_{stem}_"
    for session in sorted(KNOWN_SESSION_NAMES, key=len, reverse=True):
        if f"_{session}_" in padded:
            return session
    return None


def _latest_client_refs_by_session(
    results_dir: Path,
) -> dict[str, _ClientFileRef]:
    """Map session_name → newest client JSON ref (parsed or unreadable)."""
    latest: dict[str, _ClientFileRef] = {}
    if not results_dir.is_dir():
        return latest

    def consider(session: str, ref: _ClientFileRef) -> None:
        prev = latest.get(session)
        if prev is None or ref.path.name >= prev.path.name:
            latest[session] = ref

    for path in sorted(results_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            hint = _session_hint_from_name(path)
            if hint is not None:
                consider(
                    hint,
                    _ClientFileRef(path=path, result=None, load_error=str(exc)),
                )
            continue
        if not isinstance(raw, dict):
            hint = _session_hint_from_name(path)
            if hint is not None:
                consider(
                    hint,
                    _ClientFileRef(
                        path=path,
                        result=None,
                        load_error="Result file is not a JSON object",
                    ),
                )
            continue
        # Server-role and other non-client files are ignored for the matrix.
        if raw.get("role") != "client":
            continue

        session = str(raw.get("session_name") or "").strip() or _session_hint_from_name(
            path
        )
        if not session:
            continue

        try:
            result = ExperimentBResult.from_dict(raw)
        except (ValueError, TypeError, KeyError) as exc:
            consider(
                session,
                _ClientFileRef(path=path, result=None, load_error=str(exc)),
            )
            continue
        consider(session, _ClientFileRef(path=path, result=result))
    return latest


def validate_experiment_b_matrix(
    results_dir: Path,
    *,
    expected_schema_version: int = SCHEMA_VERSION,
    required_sessions: frozenset[str] | None = None,
) -> list[ScenarioEvidence]:
    """Validate archived client results for the required VPN scenario matrix.

    Loopback destinations or sources are never counted as two-computer PASS
    evidence (status ``INVALID``). Failed real LAN attempts remain ``FAIL``.
    """
    sessions = sorted(required_sessions or REQUIRED_SESSION_NAMES)
    latest = _latest_client_refs_by_session(results_dir)
    rows: list[ScenarioEvidence] = []

    for session in sessions:
        ref = latest.get(session)
        if ref is None:
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.MISSING,
                    path=None,
                    detail="No client result file for this scenario",
                )
            )
            continue

        if ref.result is None:
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.INVALID,
                    path=str(ref.path),
                    detail=f"Cannot read result schema: {ref.load_error or 'unknown'}",
                )
            )
            continue

        result = ref.result
        path = ref.path

        if result.role != "client":
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.INVALID,
                    path=str(path),
                    detail=f"Expected role=client, found role={result.role!r}",
                )
            )
            continue

        if result.schema_version != expected_schema_version:
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.INVALID,
                    path=str(path),
                    detail=(
                        f"schema_version {result.schema_version} incompatible with "
                        f"expected {expected_schema_version}"
                    ),
                )
            )
            continue

        source = None
        if result.local is not None:
            source = result.local.actual_source_ip or result.local.requested_source_ip
        destination = result.remote.ip if result.remote else None

        if _client_ips_are_loopback(result):
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.INVALID,
                    path=str(path),
                    detail=(
                        "Loopback address used; not valid two-computer LAN evidence "
                        f"(source={source!r}, destination={destination!r})"
                    ),
                    success=result.success,
                    source_ip=source,
                    destination_ip=destination,
                )
            )
            continue

        if result.success:
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.PASS,
                    path=str(path),
                    detail="Client echo succeeded with non-loopback endpoints",
                    success=True,
                    source_ip=source,
                    destination_ip=destination,
                )
            )
        else:
            err_code = None
            if isinstance(result.error, dict):
                err_code = result.error.get("code")
            rows.append(
                ScenarioEvidence(
                    session_name=session,
                    status=EvidenceStatus.FAIL,
                    path=str(path),
                    detail=f"Client result recorded failure ({err_code or 'unknown'})",
                    success=False,
                    source_ip=source,
                    destination_ip=destination,
                )
            )
    return rows


def format_evidence_report(rows: list[ScenarioEvidence]) -> str:
    headers = ("Scenario", "Status", "Source IP", "Destination", "Detail")
    body: list[tuple[str, str, str, str, str]] = [
        (
            row.session_name,
            row.status.value,
            row.source_ip or "-",
            row.destination_ip or "-",
            row.detail,
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
    counts = {status: 0 for status in EvidenceStatus}
    for row in rows:
        counts[row.status] += 1
    lines.append("")
    lines.append(
        "Totals: "
        + ", ".join(f"{status.value}={counts[status]}" for status in EvidenceStatus)
    )
    return "\n".join(lines)


def evidence_exit_code(rows: list[ScenarioEvidence]) -> int:
    """Return 0 only when every required scenario is PASS."""
    if not rows:
        return 1
    return 0 if all(row.status is EvidenceStatus.PASS for row in rows) else 1
