# Phase 0 experiments

This directory holds **disposable technical-validation scripts** for Phase 0.
Scripts prove risky dependencies work in isolation on Windows 11 (including with
VPNs connected) before the full application is built.

**Status:** Experiments **A**, **B**, and **C** are implemented. Experiments D–F
are **not** implemented yet.

Do not treat scripts here as production application architecture. Prefer printed
pass/fail output and optional metrics JSON. VPN / LAN failure guidance from
Experiment B lives in `docs/vpn-lan-access.md`.

## Experiment overview

| ID | Purpose | Demonstrates | Status |
|---|---|---|---|
| **A** | Adapter enumeration, classification, and bind-to-selected-IP TCP echo | Physical LAN IPv4 selection; VPN/virtual adapters visible but not preferred; listener bound to the chosen address | **Implemented** |
| **B** | Two-machine TCP connect with **both VPNs enabled** | Real LAN reachability under VPN; failure modes for allow-LAN / split-tunnel guidance | **Implemented** |
| **C** | DXcam capture → local preview + FPS/latency counters | Desktop Duplication viability | **Implemented** |
| **D** | WASAPI loopback → local playback + underrun metrics | System-audio capture | Not started |
| **E** | aiortc synthetic video track | WebRTC video / ICE host behavior | Not started |
| **F** | aiortc synthetic audio + Opus playback | WebRTC audio path | Not started |

---

## Experiment A — adapter bind / TCP echo

### Purpose

Prove that Snowlink can:

1. Enumerate active Windows IPv4 adapters with enough metadata to distinguish
   physical Ethernet/Wi-Fi from VPN, Hyper-V, WSL, Tailscale, and loopback.
2. Classify adapters (structured Windows `IF_TYPE` / tunnel metadata first;
   name heuristics second).
3. Let the operator **manually** select an adapter or IPv4 (VPN adapters are
   shown, not silently hidden).
4. Bind a TCP listener **only** to that IPv4 (never `0.0.0.0` by default).
5. Complete a length-limited UTF-8 echo round-trip as a stand-in for later
   signaling TCP.

No VPN settings, firewall rules, screen/audio capture, WebRTC, or UI are
modified or started by this experiment.

### Commands

From the repository root, with the project venv activated and
`pip install -r requirements-dev.txt` completed:

```powershell
# List adapters (human-readable)
python experiments/experiment_a_adapter_bind.py list

# List adapters as JSON
python experiments/experiment_a_adapter_bind.py list --json

# Serve: bind TCP echo to a specific LAN IPv4 (replace with your address)
python experiments/experiment_a_adapter_bind.py serve --ip 192.168.1.20 --port 3847

# Serve until Ctrl+C (multiple clients)
python experiments/experiment_a_adapter_bind.py serve --ip 192.168.1.20 --port 3847 --serve-forever

# Connect / echo from the same machine or the second PC
python experiments/experiment_a_adapter_bind.py connect --ip 192.168.1.20 --port 3847 --message "snowlink-test"

# JSON result from the client
python experiments/experiment_a_adapter_bind.py connect --ip 192.168.1.20 --port 3847 --message "snowlink-test" --json
```

Default port is **3847**. The server prints `getsockname()` after bind.

### Expected output (illustrative)

**`list`**

```text
Adapters found: 7
------------------------------------------------------------------------
[1] Ethernet
    id:          {XXXXXXXX-...}
    description: Intel(R) Ethernet Connection
    status:      up
    ifType:      6 (ETHERNET_CSMACD)
    tunnelType:  0 (NONE)
    speed_bps:   1000000000
    category:    physical_ethernet  [PREFERRED]  score=...
    ipv4:        192.168.1.20/24 (private)

[2] Corp VPN
    ...
    category:    vpn_or_tunnel  [not-preferred]  score=...
    ipv4:        10.64.8.12/32 (private)

...
Auto-selected (preferred): 192.168.1.20 on Ethernet [physical_ethernet]
```

**`serve`**

```text
Selected adapter: Ethernet [physical_ethernet]
Binding TCP echo server to 192.168.1.20:3847
Listening on 192.168.1.20:3847 (getsockname)
Waiting for a client (Ctrl+C to stop)...
Serve OK  bound=192.168.1.20:3847
```

**`connect`**

```text
Connect OK  peer=192.168.1.20:3847  echo verified
Message: 'snowlink-test'  elapsed=2.3 ms
```

JSON results include `experiment`, `timestamp`, `selected_adapter`,
`selected_ip`, `requested_port`, `actual_bound_address`, `success`,
`elapsed_connection_ms`, `error_code`, and `error_message`.

### How to test locally (one PC)

1. Run `list` and confirm your physical Ethernet or Wi-Fi adapter is
   `PREFERRED` and VPN/virtual adapters are listed as `not-preferred`.
2. Pick that LAN IPv4.
3. In terminal A: `serve --ip <lan-ip> --port 3847`
4. Confirm the printed bound address is exactly `<lan-ip>:3847`.
5. In terminal B: `connect --ip <lan-ip> --port 3847 --message "snowlink-test"`
6. Expect exit code 0 and echo verified.

Loopback sanity check (optional):

```powershell
python experiments/experiment_a_adapter_bind.py serve --ip 127.0.0.1 --port 3847
python experiments/experiment_a_adapter_bind.py connect --ip 127.0.0.1 --port 3847 --message "loopback"
```

### How to test between two computers

1. On **PC-A** (sharer stand-in): `list`, note the physical LAN IPv4 (same subnet
   as PC-B).
2. On **PC-A**: `serve --ip <pc-a-lan-ip> --port 3847 --serve-forever`
3. On **PC-B**: `connect --ip <pc-a-lan-ip> --port 3847 --message "snowlink-test"`
4. Pass: client prints `Connect OK` / `success: true`.
5. If it fails with timeout/refused while VPNs are on, record the error codes for
   Experiment B / later `docs/vpn-lan-access.md` — do **not** disable the VPN.

Windows Firewall may prompt on first listen; approve for private networks if you
intend to test cross-machine. This experiment does not create firewall rules.

### Common errors

| Code / symptom | Likely cause |
|---|---|
| `ADDR_NOT_AVAILABLE` | `--ip` is not assigned to a local adapter |
| `PORT_IN_USE` | Another process is listening on that IP:port |
| `CONNECTION_REFUSED` | Nothing listening, or firewall reset the SYN |
| `CONNECTION_TIMEOUT` | Firewall/VPN kill-switch dropping packets; wrong subnet |
| `MESSAGE_TOO_LARGE` | Payload over 4096 UTF-8 bytes |
| `SELECTION_FAILED` / no preferred adapter | Only VPN/virtual up — pass `--ip` manually |
| Enumeration failed on non-Windows | `GetAdaptersAddresses` is Windows-only |

### Pass / fail evidence

| Check | Pass | Fail |
|---|---|---|
| Adapter list on Windows 11 | Physical NIC identified; VPN/virtual visible and labeled | Crash; adapters missing; silent VPN-only view |
| Bind | `getsockname()` equals selected IP:port | Bound to `0.0.0.0` or wrong IP |
| Local echo | Client exit 0, echo matches | Mismatch / nonzero exit |
| Invalid bind IP | Clear `ADDR_NOT_AVAILABLE` (or equivalent) | Hang / unclear traceback only |
| Occupied port | Clear `PORT_IN_USE` (or equivalent) | Hang |
| Automated tests | `pytest`, `ruff check .`, `mypy` pass | Any failing |

### Automated tests

```powershell
pytest tests/unit/test_adapter_classification.py tests/unit/test_adapter_selection.py tests/integration/test_tcp_echo_local.py
ruff check .
mypy
```

Windows-specific enumeration smoke tests are skipped on non-Windows platforms.

---

## Experiment B — two-machine TCP under VPN scenarios

### Purpose

Measure LAN TCP reachability between two PCs while VPNs are off/on in four
combinations. Reuses Experiment A bind + echo. Full runbook:
[`docs/vpn-lan-access.md`](../docs/vpn-lan-access.md).

### Commands

```powershell
python experiments/experiment_b_two_machine_tcp.py guide

# Computer A
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip <A-LAN-IP> --port 3847 --session-name vpn-off-off --serve-forever

# Computer B
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <A-LAN-IP> --port 3847 --session-name vpn-off-off `
  --source-ip <B-LAN-IP> --timeout 5

python experiments/experiment_b_two_machine_tcp.py summarize `
  --results-dir experiment-results/experiment-b
```

Session names: `vpn-off-off`, `vpn-on-off`, `vpn-off-on`, `vpn-on-on`.

Results are written under gitignored `experiment-results/experiment-b/`.

### Automated tests

```powershell
pytest tests/unit/test_experiment_b_*.py tests/integration/test_experiment_b_tcp.py
```

---

## Experiment C — DXcam local screen-capture validation

### Purpose

Prove that DXcam can capture a selected Windows 11 monitor with acceptable
local capture FPS, preview FPS, frame-age / processing delay, CPU, memory,
dropped-frame behavior, and clean shutdown — enough to decide whether Snowlink
can proceed with DXcam for the Phase 1 screen-streaming prototype.

This experiment is **local only**. It does **not** stream over the network,
use WebRTC, capture system audio, or open the final Snowlink UI.

Pipeline:

```text
DXcam grab → latest-frame slot (depth 1) → letterbox scale → optional OpenCV preview → metrics
```

Scaling policy: fit inside the requested WxH while preserving aspect ratio;
letterbox with black bars (never stretch). Scaling time is measured separately
from capture time.

### Monitor index mapping

Snowlink `--monitor N` is a **logical** index (primary first, then desktop
origin). It is mapped to DXcam `(device_idx, output_idx)` by matching desktop
rectangles, then `HMONITOR`, then `\\.\DISPLAYn` device names. Do **not** assume
`--monitor` equals DXcam `output_idx`.

### Setup / dependencies

```powershell
pip install -e ".[dev,capture]"
```

This installs `dxcam[cv2,winrt]`, `opencv-python`, `numpy`, and `psutil`.

### Commands

```powershell
# List monitors, DPI, DXcam indices, backend availability
python experiments/experiment_c_screen_capture.py list

# Interactive preview (Esc or close window to stop)
python experiments/experiment_c_screen_capture.py preview `
  --monitor 0 `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --backend dxgi

# Timed benchmark (writes JSON under experiment-results/experiment-c/)
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor 0 `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --backend dxgi `
  --duration 60

# JSON to stdout as well
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor 0 --backend dxgi --fps 30 --width 1280 --height 720 `
  --duration 60 --json --no-preview

# Low / Balanced / High suite (no preview unless --show-preview)
python experiments/experiment_c_screen_capture.py suite `
  --monitor 0 `
  --backend dxgi `
  --duration-per-preset 60
```

Defaults match the Balanced Snowlink preset: **1280×720 @ 30 FPS**.

### Expected outputs

**`list`** — monitor index, name, desktop coordinates (may be negative),
width/height, primary flag, DPI when available, mapped DXcam device/output
indices, and backend availability (`dxgi` / `winrt`).

**`preview`** — OpenCV window with overlays for capture FPS, preview FPS,
dropped/null frames, and approximate local frame age. Esc / window close /
Ctrl+C release capture resources.

**`benchmark` / `suite`** — console summary plus JSON files such as:

```text
experiment-results/experiment-c/2026-08-06T160000_monitor-0_dxgi_balanced.json
```

Screenshots / frame pixels are **not** stored.

### Interpreting metrics

| Metric | How to read it |
|---|---|
| Actual capture FPS | Should be within ~10% of the requested FPS under light desktop activity for Balanced |
| Dropped / overwritten frames | Expected when preview/scale is slower than capture; depth-1 slot drops stale frames so latency does not grow |
| Frame age / capture-to-preview | Approximate **local** delay from grab timestamp to consume/render — **not** glass-to-glass latency |
| CPU / memory | Process-level via psutil; memory should not climb continuously over a 60s run |
| Null frames | DXcam returned no new frame; some nulls are normal depending on desktop damage |

Completing the High preset command does **not** by itself mean the machine
“supports” High — inspect FPS, CPU, and memory first.

### Backend comparison (DXGI vs WinRT)

When WinRT is listed as available:

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor 0 --backend dxgi --fps 30 --width 1280 --height 720 `
  --duration 60 --no-preview

python experiments/experiment_c_screen_capture.py benchmark `
  --monitor 0 --backend winrt --fps 30 --width 1280 --height 720 `
  --duration 60 --no-preview
```

Compare actual FPS, frame-age metrics, CPU, memory, cursor behavior, and
stability. Cursor compositing: DXGI does not support `--show-cursor` in DXcam;
WinRT does (via DXcam’s WinRT cursor option). Requesting `--show-cursor` with
DXGI fails clearly with `UNSUPPORTED_CURSOR_CAPTURE`.

### Common DXcam failures

| Code | Likely cause / next step |
|---|---|
| `DXCAM_NOT_INSTALLED` | `pip install -e ".[capture]"` |
| `BACKEND_UNAVAILABLE` | Try the other backend; install `dxcam[winrt]` for WinRT |
| `INVALID_MONITOR` | Re-run `list` and pick a valid index |
| `CAPTURE_INITIALIZATION_FAILED` | Monitor disconnected, exclusive fullscreen conflict, or another capture client |
| `CAPTURE_FRAME_TIMEOUT` | Lower FPS/resolution or switch backend |
| `UNSUPPORTED_CURSOR_CAPTURE` | Omit `--show-cursor` or use `--backend winrt` |
| `PREVIEW_INITIALIZATION_FAILED` | Need GUI OpenCV / active desktop; use `--no-preview` for headless metrics |

### Pass / fail criteria (experimental targets)

For the **Balanced** preset on each target PC:

1. Intended monitor can be selected.
2. Capture runs ≥ 60 seconds continuously.
3. Actual capture FPS within ~10% of 30 under light desktop activity.
4. Preview stays responsive (when used).
5. Dropped frames do not cause growing latency (depth-1 slot).
6. CPU and memory are recorded.
7. Memory does not grow continuously during the test.
8. Escape, window close, and Ctrl+C release capture resources.
9. Multi-monitor coordinates are reported correctly when applicable.
10. Automated checks pass (`pytest`, `ruff`, `mypy`).

### Automated tests

```powershell
pytest tests/unit/test_frame_slot.py tests/unit/test_capture_configuration.py `
  tests/unit/test_capture_metrics.py tests/integration/test_screen_capture_smoke.py
# Optional live DXcam grab:
pytest -m hardware
```

Normal `pytest` does not require an interactive capture window.

---

## Execution order

1. **Experiment A** first — foundation for VPN-safe networking.
2. **Experiment B** next — two-machine reachability before heavy media work.
3. **Experiment C** — local DXcam viability before WebRTC / Phase 1.
4. Then **E** and **D**/**F** for the remaining Phase 0 go/no-go gate.

## Go / no-go gate (from PLAN.md)

If Experiments **C**, **E**, and **F** meet rough latency/CPU bars for the
Balanced preset (`1280×720@30`), begin Phase 1 (screen-only prototype).
Otherwise keep the architecture but schedule a native capture/encode helper
spike before investing in full Phase 3 UI work.

## What belongs here later

When implemented, expect one script (or small pair of scripts) per experiment,
plus short result notes. Do **not** add application UI, signaling product code,
or packaging from this folder.
