"""Persist and validate Experiment C JSON result files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from snowlink.media.capture_models import (
    DEFAULT_PRESET,
    EXPERIMENT_NAME,
    SCHEMA_VERSION,
    ExperimentCResult,
)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

# Phase 0 Balanced gate targets for remediation evidence.
REQUIRED_WIDTH = DEFAULT_PRESET.width  # 1280
REQUIRED_HEIGHT = DEFAULT_PRESET.height  # 720
REQUIRED_FPS = DEFAULT_PRESET.fps  # 30
MIN_EVIDENCE_DURATION_S = 60.0
PASS_MIN_ACTUAL_FPS = 27.0
FAIL_MAX_ACTUAL_FPS = 15.0  # below this → severely under target
HIGH_CPU_AVERAGE_PERCENT = 50.0
HIGH_CPU_PEAK_PERCENT = 85.0
MEMORY_GROWTH_FAIL_MB = 100.0
DROPPED_FRAME_WARN_RATIO = 0.05
FRAME_AGE_GROW_FAIL_MS = 250.0

KNOWN_MACHINE_LABELS: tuple[str, ...] = ("computer-a", "computer-b")


def sanitize_filename_component(value: str, *, max_len: int = 64) -> str:
    """Make a path component safe for result filenames (no path separators)."""
    cleaned = value.strip().replace("..", ".")
    cleaned = _UNSAFE_FILENAME.sub("-", cleaned).strip("-._")
    cleaned = cleaned.replace("..", ".")
    if not cleaned:
        cleaned = "unnamed"
    return cleaned[:max_len]


def sanitize_machine_label(value: str, *, max_len: int = 64) -> str:
    """Normalize an operator-supplied machine label for JSON and filenames.

    Lowercases and strips unsafe characters. Does not record Windows account
    names; callers must not pass usernames or other PII.
    """
    return sanitize_filename_component(value.strip().lower(), max_len=max_len)


def result_filename(
    *,
    monitor: int,
    backend: str,
    preset_or_label: str,
    machine_label: str | None = None,
    when: datetime | None = None,
) -> str:
    """Build a sanitized Experiment C result filename."""
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%S")
    parts = [stamp]
    if machine_label:
        parts.append(sanitize_machine_label(machine_label))
    parts.extend(
        [
            f"monitor-{monitor}",
            sanitize_filename_component(backend),
            sanitize_filename_component(preset_or_label),
        ]
    )
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
            machine_label=result.machine_label,
        )
    else:
        name = filename or result_filename(
            monitor=0,
            backend="unknown",
            preset_or_label=label,
            machine_label=result.machine_label,
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


class EvidenceStatus(StrEnum):
    """Status of one required Experiment C machine against archived JSON."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class MachineEvidence:
    machine_label: str
    status: EvidenceStatus
    path: str | None
    detail: str
    duration_s: float | None = None
    actual_fps: float | None = None
    cpu_average: float | None = None
    memory_growth_mb: float | None = None
    shutdown: str | None = None
    success: bool | None = None


@dataclass(frozen=True, slots=True)
class _ResultFileRef:
    path: Path
    result: ExperimentCResult | None
    load_error: str | None = None


def _machine_hint_from_name(path: Path) -> str | None:
    stem = path.stem.lower()
    padded = f"_{stem}_"
    for label in sorted(KNOWN_MACHINE_LABELS, key=len, reverse=True):
        if f"_{label}_" in padded or stem.startswith(f"{label}_"):
            return label
        # Filename form: {stamp}_{label}_monitor-...
        if f"_{label}_monitor-" in f"_{stem}":
            return label
    return None


def actual_duration_s(result: ExperimentCResult) -> float | None:
    """Best-effort measured run duration from details or requested config."""
    raw = result.details.get("experiment_duration_s")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if result.configuration is not None:
        return float(result.configuration.duration_s)
    return None


def memory_growth_mb(result: ExperimentCResult) -> float | None:
    start = result.resources.memory_mb_start
    end = result.resources.memory_mb_end
    if start is None or end is None:
        return None
    return float(end) - float(start)


def shutdown_status(result: ExperimentCResult) -> str:
    """Infer shutdown cleanliness from success / structured errors."""
    if result.success and not result.errors:
        return "clean"
    for err in result.errors:
        code = str(err.get("code", ""))
        message = str(err.get("message", "")).lower()
        if code == "UNEXPECTED_CAPTURE_ERROR" and "ctrl+c" in message:
            return "interrupted"
        if "shutdown" in message or "release" in message:
            return "unclean"
    if result.success:
        return "clean"
    return "failed"


def is_balanced_configuration(result: ExperimentCResult) -> bool:
    cfg = result.configuration
    if cfg is None:
        return False
    if cfg.preset_name == "balanced":
        return (
            cfg.requested_width == REQUIRED_WIDTH
            and cfg.requested_height == REQUIRED_HEIGHT
            and cfg.requested_fps == REQUIRED_FPS
        )
    return (
        cfg.requested_width == REQUIRED_WIDTH
        and cfg.requested_height == REQUIRED_HEIGHT
        and cfg.requested_fps == REQUIRED_FPS
    )


def looks_synthetic_or_mocked(result: ExperimentCResult) -> str | None:
    """Return a reason string when the result appears non-hardware evidence."""
    markers = ("synthetic", "mock", "mocked", "fixture", "unit-test", "unittest")
    for note in result.notes:
        lowered = note.lower()
        if any(marker in lowered for marker in markers):
            return f"Notes indicate non-hardware evidence ({note!r})"
    details_blob = json.dumps(result.details, default=str).lower()
    if any(marker in details_blob for marker in markers):
        return "details indicate synthetic/mocked capture"
    if result.details.get("synthetic") is True or result.details.get("mocked") is True:
        return "details.synthetic/mocked flag set"
    return None


def _is_candidate_balanced_evidence(result: ExperimentCResult) -> bool:
    """Whether this file can serve as Phase 0 Balanced evidence for a machine."""
    if result.experiment != EXPERIMENT_NAME:
        return False
    if result.schema_version != SCHEMA_VERSION:
        return False
    if not is_balanced_configuration(result):
        return False
    duration = actual_duration_s(result)
    if duration is None or duration < MIN_EVIDENCE_DURATION_S:
        return False
    return looks_synthetic_or_mocked(result) is None


def _latest_refs_by_machine(
    results_dir: Path,
) -> dict[str, _ResultFileRef]:
    """Map machine_label → newest Balanced-candidate JSON ref."""
    latest: dict[str, _ResultFileRef] = {}
    if not results_dir.is_dir():
        return latest

    def consider(label: str, ref: _ResultFileRef) -> None:
        prev = latest.get(label)
        if prev is None or ref.path.name >= prev.path.name:
            latest[label] = ref

    for path in sorted(results_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            hint = _machine_hint_from_name(path)
            if hint is not None:
                consider(
                    hint,
                    _ResultFileRef(path=path, result=None, load_error=str(exc)),
                )
            continue
        if not isinstance(raw, dict):
            hint = _machine_hint_from_name(path)
            if hint is not None:
                consider(
                    hint,
                    _ResultFileRef(
                        path=path,
                        result=None,
                        load_error="Result file is not a JSON object",
                    ),
                )
            continue

        try:
            result = ExperimentCResult.from_dict(raw)
        except (ValueError, TypeError, KeyError) as exc:
            hint = _machine_hint_from_name(path)
            label = (
                sanitize_machine_label(str(raw.get("machine_label")))
                if raw.get("machine_label")
                else hint
            )
            if label in KNOWN_MACHINE_LABELS:
                consider(
                    label,
                    _ResultFileRef(path=path, result=None, load_error=str(exc)),
                )
            continue

        label_raw = result.machine_label or _machine_hint_from_name(path)
        if not label_raw:
            continue
        label = sanitize_machine_label(label_raw)
        if label not in KNOWN_MACHINE_LABELS:
            continue

        # Prefer Balanced >=60 s candidates; still keep unreadable/invalid for status.
        if result.experiment != EXPERIMENT_NAME:
            continue
        if not _is_candidate_balanced_evidence(result):
            # Keep short / wrong-config files only when nothing better exists yet,
            # so the validator can report INVALID/FAIL instead of MISSING.
            prev = latest.get(label)
            if prev is not None and prev.result is not None:
                if _is_candidate_balanced_evidence(prev.result):
                    continue
                if prev.path.name >= path.name:
                    continue
            consider(label, _ResultFileRef(path=path, result=result))
            continue

        consider(label, _ResultFileRef(path=path, result=result))
    return latest


def evaluate_experiment_c_result(result: ExperimentCResult) -> tuple[EvidenceStatus, str]:
    """Classify a single Experiment C result without mutating it."""
    if result.experiment != EXPERIMENT_NAME:
        return (
            EvidenceStatus.INVALID,
            f"Unexpected experiment name {result.experiment!r}",
        )
    if result.schema_version != SCHEMA_VERSION:
        return (
            EvidenceStatus.INVALID,
            (
                f"schema_version {result.schema_version} incompatible with "
                f"expected {SCHEMA_VERSION}"
            ),
        )

    synthetic_reason = looks_synthetic_or_mocked(result)
    if synthetic_reason is not None:
        return EvidenceStatus.INVALID, synthetic_reason

    if result.configuration is None:
        return EvidenceStatus.INVALID, "Missing configuration object"

    if not is_balanced_configuration(result):
        cfg = result.configuration
        return (
            EvidenceStatus.INVALID,
            (
                "Not Balanced Phase 0 config "
                f"(requested {cfg.requested_width}x{cfg.requested_height}"
                f"@{cfg.requested_fps}; need "
                f"{REQUIRED_WIDTH}x{REQUIRED_HEIGHT}@{REQUIRED_FPS})"
            ),
        )

    duration = actual_duration_s(result)
    if duration is None:
        return EvidenceStatus.INVALID, "Missing experiment_duration_s / duration_s"
    if duration < MIN_EVIDENCE_DURATION_S:
        return (
            EvidenceStatus.INVALID,
            f"Duration {duration:.1f}s is shorter than {MIN_EVIDENCE_DURATION_S:.0f}s",
        )

    warns: list[str] = []
    fails: list[str] = []

    if not result.success:
        fails.append("success=false")
    if result.capture.frames_captured <= 0:
        fails.append("no frames captured")
    if result.capture.native_width <= 0 or result.capture.native_height <= 0:
        fails.append("native monitor resolution missing")

    actual_fps = float(result.capture.actual_fps)
    if actual_fps < FAIL_MAX_ACTUAL_FPS:
        fails.append(f"actual FPS {actual_fps:.1f} severely below target")
    elif actual_fps < PASS_MIN_ACTUAL_FPS:
        warns.append(f"actual FPS {actual_fps:.1f} below {PASS_MIN_ACTUAL_FPS:.0f}")

    growth = memory_growth_mb(result)
    peak = result.resources.memory_mb_peak
    end = result.resources.memory_mb_end
    if growth is not None and growth >= MEMORY_GROWTH_FAIL_MB:
        # Continuous growth heuristic: large start→end rise with peak near end.
        if peak is not None and end is not None and peak <= float(end) * 1.05 + 1.0:
            fails.append(f"memory growth {growth:+.1f} MB suggests continuous climb")
        else:
            warns.append(f"memory growth {growth:+.1f} MB")

    cpu_avg = result.resources.cpu_percent_average
    cpu_peak = result.resources.cpu_percent_peak
    if cpu_avg is not None and float(cpu_avg) >= HIGH_CPU_AVERAGE_PERCENT:
        warns.append(f"high CPU average {float(cpu_avg):.1f}%")
    elif cpu_peak is not None and float(cpu_peak) >= HIGH_CPU_PEAK_PERCENT:
        warns.append(f"high CPU peak {float(cpu_peak):.1f}%")

    overwritten = result.capture.overwritten_frames
    captured = max(result.capture.frames_captured, 1)
    drop_ratio = overwritten / captured
    frame_age_p95 = result.timing_ms.frame_age_p95
    if drop_ratio >= DROPPED_FRAME_WARN_RATIO:
        if (
            frame_age_p95 is not None
            and float(frame_age_p95) >= FRAME_AGE_GROW_FAIL_MS
        ):
            fails.append(
                f"dropped frames ({overwritten}) with high frame-age p95 "
                f"{float(frame_age_p95):.1f} ms"
            )
        else:
            warns.append(
                f"dropped/overwritten frames={overwritten} without growing latency"
            )

    if result.configuration.cursor_requested:
        for err in result.errors:
            if str(err.get("code", "")) == "UNSUPPORTED_CURSOR_CAPTURE":
                warns.append("cursor support missing for requested backend")
                break

    persistent_codes = {
        "CAPTURE_INITIALIZATION_FAILED",
        "CAPTURE_FRAME_TIMEOUT",
        "BACKEND_UNAVAILABLE",
        "DXCAM_NOT_INSTALLED",
        "INVALID_MONITOR",
    }
    for err in result.errors:
        code = str(err.get("code", ""))
        if code in persistent_codes:
            fails.append(f"persistent capture error {code}")

    shut = shutdown_status(result)
    if shut not in {"clean"}:
        if shut == "interrupted":
            fails.append("run interrupted before clean completion")
        elif not result.success:
            fails.append(f"shutdown={shut}")

    if fails:
        return EvidenceStatus.FAIL, "; ".join(fails)
    if warns:
        return EvidenceStatus.WARN, "; ".join(warns)
    return EvidenceStatus.PASS, "Balanced >=60 s capture meets Phase 0 gate"


def validate_experiment_c_machines(
    results_dir: Path,
    *,
    required_machines: tuple[str, ...] = KNOWN_MACHINE_LABELS,
) -> list[MachineEvidence]:
    """Validate archived Balanced evidence for each required machine label."""
    latest = _latest_refs_by_machine(results_dir)
    rows: list[MachineEvidence] = []

    for machine in required_machines:
        ref = latest.get(machine)
        if ref is None:
            rows.append(
                MachineEvidence(
                    machine_label=machine,
                    status=EvidenceStatus.MISSING,
                    path=None,
                    detail=(
                        "No Balanced >=60 s result with this --machine-label "
                        f"({machine})"
                    ),
                )
            )
            continue

        if ref.result is None:
            rows.append(
                MachineEvidence(
                    machine_label=machine,
                    status=EvidenceStatus.INVALID,
                    path=str(ref.path),
                    detail=f"Cannot read result schema: {ref.load_error or 'unknown'}",
                )
            )
            continue

        result = ref.result
        status, detail = evaluate_experiment_c_result(result)
        rows.append(
            MachineEvidence(
                machine_label=machine,
                status=status,
                path=str(ref.path),
                detail=detail,
                duration_s=actual_duration_s(result),
                actual_fps=float(result.capture.actual_fps),
                cpu_average=(
                    None
                    if result.resources.cpu_percent_average is None
                    else float(result.resources.cpu_percent_average)
                ),
                memory_growth_mb=memory_growth_mb(result),
                shutdown=shutdown_status(result),
                success=result.success,
            )
        )
    return rows


def format_experiment_c_evidence_report(rows: list[MachineEvidence]) -> str:
    headers = (
        "Computer",
        "Status",
        "Duration",
        "Actual FPS",
        "Memory Growth",
        "Shutdown",
    )
    body: list[tuple[str, str, str, str, str, str]] = []
    for row in rows:
        duration = "-" if row.duration_s is None else f"{row.duration_s:.1f} s"
        fps = "-" if row.actual_fps is None else f"{row.actual_fps:.1f} FPS"
        growth = (
            "-"
            if row.memory_growth_mb is None
            else f"{row.memory_growth_mb:+.1f} MB"
        )
        body.append(
            (
                row.machine_label,
                row.status.value,
                duration,
                fps,
                growth,
                row.shutdown or "-",
            )
        )

    widths = [len(h) for h in headers]
    for line in body:
        for i, cell in enumerate(line):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt(headers), fmt(tuple("-" * w for w in widths))]
    lines.extend(fmt(row) for row in body)
    lines.append("")
    for row in rows:
        path = row.path or "(none)"
        lines.append(f"{row.machine_label}: {row.status.value} - {row.detail}")
        lines.append(f"  file: {path}")
        if row.cpu_average is not None:
            lines.append(f"  cpu_avg: {row.cpu_average:.1f}%")
    counts = {status: 0 for status in EvidenceStatus}
    for row in rows:
        counts[row.status] += 1
    lines.append("")
    lines.append(
        "Totals: "
        + ", ".join(f"{status.value}={counts[status]}" for status in EvidenceStatus)
    )
    return "\n".join(lines)


def evidence_exit_code(rows: list[MachineEvidence]) -> int:
    """Return 0 when every required machine has sufficient evidence (PASS or WARN)."""
    if not rows:
        return 1
    ok = {EvidenceStatus.PASS, EvidenceStatus.WARN}
    return 0 if all(row.status in ok for row in rows) else 1
