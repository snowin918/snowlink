# Snowlink

Private LAN screen and system-audio share for Windows 11 (exactly two peers).

**Phase 1 screen-only demo:** Share / View over LAN (HTTP signaling, no pairing).
System audio and pairing codes are not ready yet (Phase 2 / 3). Phase 0 gate is
`GO` with constraints — see `docs/phase-0-go-no-go.md` (default capture preset
is **Low** because Balanced may miss ~30 FPS on software capture).

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

# App shell + Phase 0/1 extras (recommended on a lab PC)
pip install -e ".[dev,ui,capture,audio,webrtc]"
```

Runtime-only install (no pytest/ruff/mypy):

```powershell
pip install -r requirements.txt
```

## Run the GUI

```powershell
pip install -e ".[ui,capture,webrtc]"
python -m snowlink
```

Or use the console script after editable install: `snowlink`.

**Works now**

- Home / Share / View / Diagnostics navigation
- **Share:** Start Sharing / Stop (DXcam → WebRTC VP8 on selected LAN IP)
- **View:** Connect / Disconnect (remote screen in the View page)
- Share: local Experiment C preview still available
- Diagnostics: run Phase 0 Experiments **A–F**

**Not ready yet**

- Pairing codes / product WebSocket signaling (Phase 3)
- System audio over the share (Phase 2)
- Full stats panel / Settings

### Two-PC GUI checklist (vpn-on-on)

1. Enable VPN on both PCs; enable Allow LAN / split-tunnel if needed (`docs/vpn-lan-access.md`).
2. On each PC: `pip install -e ".[ui,capture,webrtc]"` then `python -m snowlink`.
3. Share: pick physical LAN adapter + monitor + preset (default **low**) → Start Sharing.
4. View: enter sharer LAN IP + port (default 3847) → Connect → confirm remote screen.
5. Stop Sharing / Disconnect on both sides.

## Phase 1 CLI (no GUI)

```powershell
# Sharer (bind to physical LAN IPv4)
python -m snowlink share --bind-ip 192.168.1.25 --port 3847 --preset low

# Viewer
python -m snowlink view --remote-ip 192.168.1.25 --port 3847
```

## Build the GUI app (windowed)

```powershell
# Recommended: include capture/audio/webrtc so Diagnostics tabs work in the dist
pip install -e ".[dev,ui,capture,audio,webrtc]"

.\scripts\dev\build_gui_exe.ps1
# or:
python scripts/dev/build_gui_exe.py
```

Output folder:

```text
packaging/dist/Snowlink/Snowlink.exe
```

Distribute the **entire** `Snowlink\` folder (onedir layout), not only the `.exe`.

## Build Phase 0 console exe (A + B only)

```powershell
.\scripts\dev\build_phase0_exe.ps1
# or:
python scripts/dev/build_phase0_exe.py
```

Output: `packaging/dist/snowlink-phase0.exe` (console launcher for Experiments A and B).
This is **not** the GUI — use `build_gui_exe` for the windowed app.

## Tests and quality checks

With the virtual environment activated:

```powershell
# Unit / integration tests
pytest

# Lint
ruff check .

# Type check (package under src/)
mypy src
```

## Project layout

```text
src/snowlink/     Installable application package (includes ui/)
tests/            Automated tests
experiments/      Phase 0 validation scripts (A–F)
docs/adr/         Architecture Decision Records
docs/runbooks/    Operational runbooks (incl. Phase 0 evidence)
scripts/          Dev, packaging, and firewall helpers
packaging/        PyInstaller / installer artifacts
config/           Default non-secret configuration
```

See `PLAN.md` for the full engineering plan. Phase 0 Experiments A–F live under
`experiments/`; see `experiments/README.md`, `docs/vpn-lan-access.md`, and
`docs/runbooks/phase-0-evidence-remediation.md`.

Capture / audio / WebRTC extras:

```powershell
pip install -e ".[dev,capture]"
pip install -e ".[dev,audio]"
pip install -e ".[dev,webrtc]"
```
