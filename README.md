# Snowlink

Private LAN screen and system-audio share for Windows 11 (exactly two peers).

**MVP product:** Share / View over LAN with **screen + system audio**,
**WebSocket signaling**, **6-digit pairing + on-sharer approval**, diagnostics,
stats (incl. CPU/RSS), and portable PyInstaller onedir. Phase 0 gate is `GO`
with constraints — see `docs/phase-0-go-no-go.md` (default capture preset is
**Low** because Balanced may miss ~30 FPS on software capture). Ship evidence:
`docs/runbooks/mvp-ship-evidence.md`.

## Portable app (no Python)

1. Build (or unzip) the onedir folder — see [Build the GUI app](#build-the-gui-app-windowed).
2. Copy the entire `Snowlink\` folder to the other PC (not only `Snowlink.exe`).
3. Run `Snowlink.exe` (no Administrator required for normal use).
4. **Share PC:** Home → Share This Computer → pick ★ LAN adapter + Bind IPv4 → Start Sharing → note the 6-digit code.
5. **View PC:** Home → View Another Computer → enter IP, port `3847`, and code → Connect → Approve on the sharer.
6. Stop Sharing / Disconnect when finished.

Config and logs: `%LOCALAPPDATA%\Snowlink\`. Mid-session monitor or audio changes: Stop Sharing, re-select, Start Sharing again. Ship checklist: `docs/runbooks/ship-checklist.md`.

## Requirements

- Windows 11 (target platform)
- Python 3.12 or newer (dev / editable installs only; portable exe does not need Python)

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

# App shell + Phase 0/2 extras (recommended on a lab PC)
pip install -e ".[dev,ui,capture,audio,webrtc]"
```

Runtime-only install (no pytest/ruff/mypy):

```powershell
pip install -r requirements.txt
```

## Run the GUI

```powershell
pip install -e ".[ui,capture,audio,webrtc]"
python -m snowlink
```

Or use the console script after editable install: `snowlink`.

**Works now**

- Home / Share / View / Diagnostics / Settings navigation (Home focuses on Share + View)
- **Share (simple):** shows this PC’s address, screen picker, audio toggle, pairing code; Start / Stop; Approve when a viewer waits
- **Share (Advanced):** adapter, bind IP, quality, capture backend, port, local preview
- **Pairing:** 6-digit code on sharer; viewer enters code; sharer Approve / Deny
- **View (simple):** other PC’s address + pairing code; Connect / Disconnect; Mute; Fullscreen
- **View (Advanced):** port, source IP, playback device
- **Connection details** panel (collapsed by default; compact or full metrics)
- **Settings** persisted under `%LOCALAPPDATA%\Snowlink\config.toml`
- **Diagnostics:** connectivity checklist by default; Lab Phase 0 A–F behind “Show lab tools”
- Structured logging with secret redaction under `%LOCALAPPDATA%\Snowlink\logs\`
- Ordered app shutdown via `ShutdownCoordinator` (stop sessions → persist prefs → flush logs)
- Quality presets: Lower quality / Balanced / **Higher quality (experimental)** — software VP8 at 1080p30 is CPU-heavy

**Reliability / packaging**

- ICE disconnect recovery (`reconnecting`) on Share/View
- Viewer signaling connect retries with exponential backoff
- Bind-IP disappearance fails share with VPN/LAN guidance (`docs/vpn-lan-access.md`)
- Audio / monitor loss: actionable stop — re-select device and Start Sharing again
- Portable PyInstaller onedir — `docs/runbooks/ship-checklist.md`
- Soak sampler: `python scripts/dev/soak_sample.py --pid <PID> …`
- Acceptance / evidence: `docs/runbooks/mvp-acceptance.md`, `docs/runbooks/mvp-ship-evidence.md`

### Two-PC GUI checklist (vpn-on-on)

1. Enable VPN on both PCs; enable Allow LAN / split-tunnel if needed (`docs/vpn-lan-access.md`).
2. On each PC: run portable `Snowlink.exe`, or `pip install -e ".[ui,capture,audio,webrtc]"` then `python -m snowlink`.
3. Share: pick ★ physical LAN adapter + Bind IPv4 + monitor + loopback + preset (default **low**) → Start Sharing → note **pairing code**.
4. View: enter sharer LAN IP + port (default 3847) + pairing code → Connect.
5. Sharer: **Approve** the viewer → confirm remote screen + audio (keep gain low).
6. Stop Sharing / Disconnect on both sides.

## Share / View CLI (no GUI)

```powershell
# Sharer (bind to physical LAN IPv4; --auto-approve for lab/tests only)
python -m snowlink share --bind-ip 192.168.1.25 --port 3847 --preset low

# Viewer (pairing code printed / shown on sharer)
python -m snowlink view --remote-ip 192.168.1.25 --port 3847 --pairing-code 483920

# Video-only
python -m snowlink share --bind-ip 192.168.1.25 --no-audio --auto-approve
python -m snowlink view --remote-ip 192.168.1.25 --no-audio --pairing-code 483920
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
Optional zip: `packaging/dist/Snowlink-MVP-portable.zip`.

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
LICENSE           Proprietary license text
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
