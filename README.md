# Snowlink

Private LAN screen and system-audio share for Windows 11 (exactly two peers).

This repository is in early setup. The package entry point prints an
initialization message only — it does not start networking or capture devices.

## Requirements

- Windows 11 (target platform)
- Python 3.12 or newer

## Dependency policy

**`pyproject.toml` is the single source of truth** for package metadata and
dependency versions.

| File | Role |
|---|---|
| `pyproject.toml` | Authoritative project config and dependency declarations |
| `requirements.txt` | Thin shim: `pip install -e .` (no version pins) |
| `requirements-dev.txt` | Thin shim: `pip install -e ".[dev]"` (no version pins) |

Do not duplicate version pins across files. Add or change dependencies only in
`pyproject.toml`, then install via the requirements shims or the commands below.

## Setup (PowerShell)

From the repository root. Prefer an explicit 3.12+ interpreter (`py -3.12`) if
the default `python` on PATH is older:

```powershell
# Create and activate a virtual environment (Python 3.12+)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade packaging tools (recommended)
python -m pip install --upgrade pip setuptools wheel

# Install the project with development tools
pip install -r requirements-dev.txt
```

Runtime-only install (no pytest/ruff/mypy):

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python -m snowlink
```

Expected output:

```text
Snowlink initialized. Ready for development.
```

## Tests and quality checks

With the virtual environment activated:

```powershell
# Unit / integration tests
pytest

# Lint
ruff check .

# Type check (package under src/)
mypy
```

## Project layout

```text
src/snowlink/     Installable application package
tests/            Automated tests
experiments/      Phase 0 validation scripts (not implemented yet)
docs/adr/         Architecture Decision Records
docs/runbooks/    Operational runbooks
scripts/          Dev, packaging, and firewall helpers
packaging/        PyInstaller / installer artifacts
config/           Default non-secret configuration
```

See `PLAN.md` for the full engineering plan. Phase 0 networking and capture
experiments are documented under `experiments/README.md` and are not part of
this skeleton.
