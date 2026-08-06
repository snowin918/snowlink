# Phase 0 experiments

This directory holds **disposable technical-validation scripts** for Phase 0.
Scripts prove risky dependencies work in isolation on Windows 11 (including with
VPNs connected) before the full application is built.

## Status

Experiments **A**, **B**, **C**, **D**, **E**, and **F** are implemented.

Do not treat scripts here as production application architecture. Prefer printed
pass/fail output and optional metrics JSON. VPN / LAN failure guidance from
Experiment B lives in `docs/vpn-lan-access.md`.

## Experiment overview

| ID | Purpose | Demonstrates | Status |
|---|---|---|---|
| **A** | Adapter enumeration, classification, and bind-to-selected-IP TCP echo | Physical LAN IPv4 selection; VPN/virtual adapters visible but not preferred; listener bound to the chosen address | **Implemented** |
| **B** | Two-machine TCP connect with **both VPNs enabled** | Real LAN reachability under VPN; failure modes for allow-LAN / split-tunnel guidance | **Implemented** |
| **C** | DXcam capture → local preview + FPS/latency counters | Desktop Duplication viability | **Implemented** |
| **D** | WASAPI loopback → local playback + underrun metrics | System-audio capture | **Implemented** |
| **E** | aiortc synthetic video track | WebRTC video / ICE host behavior | **Implemented** |
| **F** | aiortc synthetic audio + Opus playback | WebRTC audio path | **Implemented** |

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

## Experiment D — WASAPI system-audio loopback validation

### Purpose

Prove that PyAudioWPatch can capture Windows system audio via WASAPI loopback
from a selected output endpoint, convert it to a Snowlink-friendly PCM format
(48 kHz / stereo / 20 ms frames), optionally play it locally, and report
bounded-buffer underrun/overrun metrics, CPU, and memory — enough to decide
whether Snowlink can proceed with WASAPI loopback for Phase 1 audio.

This experiment is **local only**. It does **not** stream over the network,
encode Opus, use WebRTC, or open the final Snowlink UI.

Pipeline:

```text
WASAPI loopback → PCM callback → bounded ring buffer (drop-oldest)
→ format/channel convert → resample to 48 kHz → 20 ms frames (sample-driven PTS)
→ optional local playback → metrics
```

### What WASAPI loopback is

A WASAPI **loopback** endpoint captures whatever is currently playing through a
Windows **output** device (speakers/headphones). It is **not** a microphone.
Snowlink must never select a microphone for system-audio capture. Protected /
DRM audio may appear as silence on some configurations.

### Silence vs underrun

| Situation | Meaning |
|---|---|
| Valid silence | Capture delivered all-zero (or near-zero) PCM — normal when nothing is playing |
| Underrun | Ring buffer had no data in time — *missing* data; pipeline emits a silence frame and keeps PTS continuous |
| DRM / protected audio | May capture as silence; not treated as a pipeline error by itself |

### Setup / dependencies

```powershell
pip install -e ".[dev,audio]"
```

This installs `PyAudioWPatch`, `av` (PyAV), `numpy`, and `psutil`.

### Commands

```powershell
# List endpoints (loopback vs physical output vs microphones)
python experiments/experiment_d_audio_loopback.py list

# Capture only (no playback) — play non-DRM system audio while this runs
python experiments/experiment_d_audio_loopback.py monitor `
  --capture-device default `
  --duration 30

# Capture + local playback (prefer headphones; gain is software-only)
python experiments/experiment_d_audio_loopback.py playback `
  --capture-device default `
  --playback-device default `
  --duration 60 `
  --gain 0.5

# Timed benchmark (writes JSON under experiment-results/experiment-d/)
python experiments/experiment_d_audio_loopback.py benchmark `
  --capture-device default `
  --playback-device default `
  --duration 60 `
  --sample-rate 48000 `
  --channels 2 `
  --frame-ms 20 `
  --buffer-ms 160 `
  --json

# Optional coarse latency helper (requires typing YES; does not claim precision)
python experiments/experiment_d_audio_loopback.py latency `
  --capture-device default `
  --playback-device default `
  --duration 20
```

Mute local playback without stopping capture: add `--muted`.

### Device selection

1. Run `list`.
2. Find the **WASAPI loopback capture endpoints** section (names often contain
   `[Loopback]`).
3. Match the loopback row to the physical output you are using (associated
   output name / default output flag).
4. Pass that loopback index as `--capture-device`, or use `default` for the
   default WASAPI output’s loopback analogue.
5. For `--playback-device`, pick a **physical output** (not a loopback, not a
   microphone). Prefer headphones.

### Use-headphones warning

Playing loopback through speakers can create echo/feedback if the same physical
endpoint is used for capture and playback. The program prints warnings when
that risk is detected. It does **not** raise Windows master volume.

### Interpreting buffer metrics

| Metric | How to read it |
|---|---|
| Buffer fill / queue delay | Approximate **local pipeline queue delay** (ring fill) — **not** true end-to-end audio latency |
| Underruns | Missing data for a frame interval; a few at startup can be OK; continuous underruns are a failure |
| Overruns / dropped samples | Oldest audio dropped to bound latency when the buffer is full |
| Non-silent vs silence frames | Non-silent should rise when ordinary non-DRM audio is playing |

### Expected outputs

**`list`** — device index, name, host API, channel counts, default rate, WASAPI
flag, loopback flag, associated physical output, default-output flag, capture /
playback usability, grouped by kind.

**`monitor`** — periodic peak/RMS/fill/underrun lines; no raw PCM printed.

**`benchmark`** — console summary plus JSON such as:

```text
experiment-results/experiment-d/2026-08-06T170000_loopback-default_48k_stereo.json
```

PCM / WAV files are **not** stored unless you add a future explicit recording
path (not part of this experiment).

### Common errors

| Code | Likely cause / next step |
|---|---|
| `PYAUDIO_WPATCH_NOT_INSTALLED` | `pip install -e ".[audio]"` |
| `WASAPI_NOT_AVAILABLE` | Confirm Windows audio stack; re-run `list` |
| `NO_LOOPBACK_DEVICE` / `INVALID_CAPTURE_DEVICE` | Pick a loopback endpoint from `list`, not a microphone |
| `INVALID_PLAYBACK_DEVICE` | Pick a physical output from `list` |
| `CAPTURE_OPEN_FAILED` / `PLAYBACK_OPEN_FAILED` | Device exclusive lock / disconnected — re-run `list` |
| `DEVICE_DISCONNECTED` | Endpoint changed; re-run `list` and select again |
| `RESAMPLE_FAILED` | Install/upgrade PyAV (`av`) via `.[audio]` |

Underruns/overruns are normally metrics/warnings, not immediate fatal errors.

### DRM limitation

Some protected media paths may yield silence on loopback. Treat that as a
platform limitation, not necessarily a Snowlink bug, when ordinary non-DRM
audio captures correctly.

### Pass / fail criteria

1. Active Windows output and its loopback counterpart are listed.
2. Ordinary non-DRM system audio produces non-silent captured frames.
3. Capture runs continuously for ≥ 60 seconds.
4. Optional local playback is understandable and mostly continuous.
5. 48 kHz conversion works.
6. Audio PTS increases continuously by output sample count.
7. Buffer growth remains bounded (drop-oldest).
8. Underrun and overrun metrics are reported.
9. CPU and memory are recorded.
10. Ctrl+C and duration completion release audio resources.
11. Automated checks pass (`pytest`, `ruff`, `mypy`).

### Automated tests

```powershell
pytest tests/unit/test_audio_ring_buffer.py tests/unit/test_audio_format.py `
  tests/unit/test_audio_metrics.py tests/integration/test_audio_pipeline_synthetic.py
# Optional live WASAPI:
pytest -m hardware
```

Normal `pytest` does not require speakers, a loopback device, or interactive
playback.

---

## Experiment E — synthetic WebRTC video (aiortc)

### Purpose

Prove that aiortc can exchange a **synthetic** VP8 video stream between two
Windows 11 peers over **host ICE candidates** on the physical LAN (including
with both VPNs enabled), with offer/answer signaling, ICE/candidate diagnostics,
frame metrics, and clean shutdown.

This experiment does **not** use DXcam, system audio, Opus, production pairing,
or the final PySide6 UI. Signaling is **experiment-only** and insecure.

```text
Experiment-only signaling: no production authentication.
Use only on your private LAN.
```

Pipeline:

```text
SyntheticVideoTrack → aiortc VP8 encode → WebRTC UDP/RTP (host ICE)
Receiver track.recv() → latest-frame slot → optional OpenCV preview → metrics
Signaling: HTTP offer/answer on sender --bind-ip (TCP only)
```

### Setup / dependencies

```powershell
pip install -e ".[dev,webrtc]"
```

This installs `aiortc`, `aiohttp`, `av` (PyAV), `opencv-python`, `numpy`, and
`psutil`.

### Commands

```powershell
# Printed guide (exact A/B steps)
python experiments/experiment_e_webrtc_video.py guide

# Sender (Computer A) — bind signaling only to the physical LAN IPv4
python experiments/experiment_e_webrtc_video.py send `
  --bind-ip 192.168.1.25 `
  --port 3848 `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --duration 120 `
  --session-name vpn-on-on

# Receiver (Computer B)
python experiments/experiment_e_webrtc_video.py receive `
  --remote-ip 192.168.1.25 `
  --port 3848 `
  --source-ip 192.168.1.30 `
  --duration 120 `
  --session-name vpn-on-on

# Headless metrics / JSON
python experiments/experiment_e_webrtc_video.py receive `
  --remote-ip 192.168.1.25 `
  --port 3848 `
  --source-ip 192.168.1.30 `
  --duration 600 `
  --no-preview `
  --json
```

Default port is **3848**. Preview closes on Escape. Ctrl+C and duration
completion shut down cleanly.

### Both-VPN test instructions

1. Confirm Experiment B `vpn-on-on` TCP reachability first when possible.
2. On each PC, run Experiment A `list` and note the **physical** LAN IPv4
   (PREFERRED ethernet/wifi) — not the VPN address.
3. Enable both VPNs; keep allow-LAN / split-tunnel settings as you intend to use
   them in production.
4. Start sender on Computer A with `--bind-ip <A-LAN-IP>`.
5. Start receiver on Computer B with `--remote-ip <A-LAN-IP>` and
   `--source-ip <B-LAN-IP>`.
6. Confirm ICE `connected`/`completed`, visible synthetic video, and that the
   **selected candidate pair** uses the physical LAN IPs (or that a mismatch
   warning is printed).

### Reading ICE candidates and the selected pair

On start, both peers print available video codecs. Results JSON include:

| Field | Meaning |
|---|---|
| `connection.local_candidates` | Host candidates gathered locally (IP/port/protocol/type + adapter category) |
| `connection.selected_local_candidate` | Local side of the selected ICE pair |
| `connection.selected_remote_candidate` | Remote side of the selected ICE pair |
| `connection.candidate_matches_requested_lan_ip` | Whether selected local IP equals `--bind-ip` / `--source-ip` |

If ICE selects a VPN adapter, Experiment E reports `ICE_SELECTED_WRONG_INTERFACE`
as a **warning** (connection may still succeed). That is a diagnostic result —
not a silent success.

### Interpreting network metrics

| Metric | How to read it |
|---|---|
| RTT (`current_rtt_ms`) | WebRTC round-trip estimate when available |
| Jitter | Packet timing variation (ms) |
| Packets lost | RTP loss from `getStats()` when present |
| Bitrate | Estimated from stats when present |
| Received / rendered FPS | Should stay within ~10% of requested under light load |

### Latency caveats

Monotonic clocks on two machines are **not** comparable. Do **not** subtract
sender `mono_ns` overlays from receiver time for one-way latency. Use:

* WebRTC RTT
* Frame inter-arrival intervals
* Rendering delay after reception
* Optional approximate clock-offset from signaling ping/pong (labeled uncertain)
* A phone-recorded visual timer for manual glass-to-glass checks

### Firewall / VPN failure symptoms

| Symptom | Likely cause |
|---|---|
| `SIGNALING_CONNECTION_FAILED` / timeout | TCP to `--bind-ip:port` blocked; wrong IP; sender not running |
| `ICE_CONNECTION_FAILED` | UDP/RTP blocked between LAN IPs (firewall or VPN kill-switch) |
| `ICE_SELECTED_WRONG_INTERFACE` | Connected via VPN/virtual adapter instead of requested LAN IP |
| `VIDEO_FRAME_TIMEOUT` | ICE looked up but media UDP stalled |

Do **not** disable VPN security to “make it work”. Record the error codes and
adjust allow-LAN / firewall rules intentionally.

### Pass / fail criteria

1. Synthetic VP8 works locally (two processes).
2. Synthetic VP8 works between the two target computers.
3. Works with both VPNs on, **or** diagnostics clearly identify the UDP/ICE block.
4. ICE states and candidates are recorded; selected pair is visible.
5. Selected pair uses the intended physical LAN path, or mismatch is reported.
6. Received FPS within ~10% of requested under light load.
7. Missing/dropped frames do not cause growing latency (latest-frame slot).
8. CPU/memory recorded; 10-minute run shows no continuous memory growth.
9. Ctrl+C, Escape, and duration completion close resources.
10. `pytest`, Ruff, and mypy pass.
11. No DXcam / system audio / production pairing / final UI was added here.

### Automated tests

```powershell
pytest tests/unit/test_synthetic_video.py tests/unit/test_ice_diagnostics.py `
  tests/unit/test_webrtc_metrics.py tests/unit/test_signaling_e.py `
  tests/unit/test_codec_preference.py tests/unit/test_remote_video_consumer.py `
  tests/integration/test_webrtc_video_local.py
# Optional real two-machine:
pytest -m network
```

Normal `pytest` does not require two computers or an interactive preview.

---

## Experiment F — synthetic WebRTC Opus audio (aiortc)

### Purpose

Prove that aiortc can exchange a **synthetic** Opus audio stream between two
Windows 11 peers over **host ICE candidates** on the physical LAN (including
with both VPNs enabled), with 48 kHz / 20 ms frames, sample-driven PTS, bounded
receiver buffering, tone verification, and optional low-gain playback.

This experiment does **not** capture microphone or system audio, does not use
DXcam, and does not add production pairing or the final PySide6 UI. Signaling is
**experiment-only** and insecure.

```text
Experiment-only signaling: no production authentication.
Use only on your private LAN.
```

**SAFE VOLUME WARNING:** When playback is enabled, a synthetic tone plays through
the selected speakers. Keep gain low (default `0.25`). Do not raise Windows
master volume for this test.

Pipeline:

```text
SyntheticAudioTrack (s16 / 48 kHz / 20 ms) → aiortc Opus → WebRTC UDP/RTP (host ICE)
Receiver track.recv() → bounded ring buffer → optional WASAPI playback → metrics
Signaling: HTTP offer/answer on sender --bind-ip (reuses Experiment E signaling)
```

### Setup / dependencies

```powershell
pip install -e ".[dev,webrtc]"
# Audible playback also needs:
pip install -e ".[audio]"
```

### Commands

```powershell
# Printed guide (exact A/B steps)
python experiments/experiment_f_webrtc_audio.py guide

# Sender (Computer A)
python experiments/experiment_f_webrtc_audio.py send `
  --bind-ip 192.168.1.25 `
  --port 3849 `
  --tone-frequency 440 `
  --sample-rate 48000 `
  --channels 2 `
  --frame-ms 20 `
  --duration 120 `
  --session-name vpn-on-on

# Receiver (Computer B) with conservative playback gain
python experiments/experiment_f_webrtc_audio.py receive `
  --remote-ip 192.168.1.25 `
  --port 3849 `
  --source-ip 192.168.1.30 `
  --playback-device default `
  --gain 0.25 `
  --duration 120 `
  --session-name vpn-on-on

# Receiver without audible playback (metrics only)
python experiments/experiment_f_webrtc_audio.py receive `
  --remote-ip 192.168.1.25 `
  --port 3849 `
  --source-ip 192.168.1.30 `
  --no-playback `
  --duration 600 `
  --json
```

Default port is **3849**. Default signal is a **440 Hz sine** at **15% digital
amplitude**, stereo, 48 kHz, 20 ms frames (960 samples/channel).

### Signal modes

| `--signal` | Behavior |
|---|---|
| `sine` | Continuous tone at `--tone-frequency` (default) |
| `silence` | All-zero PCM; PTS still advances by 960 |
| `pulse` | Periodic click every `--pulse-interval-ms` |
| `alternating` | 500 ms tone / 500 ms silence |

### Opus, 48 kHz, and sample-driven PTS

* Available audio codecs are printed before connect. Opus is preferred explicitly.
* If Opus is missing, the experiment fails with `OPUS_UNAVAILABLE` (no PCMU/PCMA fallback).
* Canonical frames: `s16`, stereo, 48_000 Hz, 960 samples/channel, `time_base=1/48000`.
* First PTS is `0`; each ordinary frame advances PTS by exactly `960`. Wall-clock
  time is never used as PTS. Late generation preserves the continuous sample
  timeline and increments late-generation counters.

### Reading ICE candidates and the selected pair

Same fields as Experiment E (`connection.selected_*_candidate`,
`candidate_matches_requested_lan_ip`). VPN adapter selection is reported as
`ICE_SELECTED_WRONG_INTERFACE` (warning / diagnostic), not hidden.

### Interpreting jitter, RTT, underruns, and tone checks

| Metric | How to read it |
|---|---|
| RTT (`current_rtt_ms`) | WebRTC round-trip estimate when available |
| Jitter | Packet timing variation (ms) |
| `local_receiver_buffering_delay_ms` | Local ring-buffer depth — **not** end-to-end latency |
| Underruns | Playback needed data; silence inserted |
| Overruns | Buffer full; oldest samples dropped (bounded) |
| `estimated_frequency_hz` | FFT/ZCR estimate; expect ~435–445 for 440 Hz sine |

### Both-VPN test procedure

1. Confirm Experiment B `vpn-on-on` TCP reachability when possible.
2. Use Experiment A `list` to pick physical LAN IPv4s on each PC.
3. Enable both VPNs; keep allow-LAN / split-tunnel as intended.
4. Start sender on A with `--bind-ip <A-LAN-IP>`.
5. Start receiver on B with `--remote-ip <A-LAN-IP>` and `--source-ip <B-LAN-IP>`.
6. Confirm Opus selected, ICE connected, LAN candidate pair, continuous audio,
   bounded buffer, zero (or near-zero) PTS errors, clean shutdown.

### Common failures

| Symptom | Likely cause |
|---|---|
| `OPUS_UNAVAILABLE` | aiortc/PyAV missing Opus |
| `SIGNALING_CONNECTION_FAILED` | TCP to `--bind-ip:port` blocked / wrong IP |
| `ICE_CONNECTION_FAILED` | UDP/RTP blocked between LAN IPs |
| `ICE_SELECTED_WRONG_INTERFACE` | VPN/virtual adapter selected |
| `FIRST_AUDIO_FRAME_TIMEOUT` | Media UDP stalled after ICE looked up |
| `PLAYBACK_OPEN_FAILED` | Use `--no-playback` to isolate receive path |

### Pass / fail criteria

1. Opus available and selected.
2. Synthetic audio works locally and between the two computers.
3. Works with both VPNs on, **or** diagnostics clearly identify the block.
4. Selected candidate pair recorded; LAN path confirmed or mismatch reported.
5. Received audio at 48 kHz; PTS continuous / sample-driven.
6. 440 Hz tone detected within reasonable tolerance.
7. Playback understandable and mostly continuous at low gain.
8. Receiver buffering bounded; underruns/overruns recorded.
9. 10-minute run shows no continuous memory growth.
10. Ctrl+C / duration completion release resources.
11. `pytest`, Ruff, and mypy pass.
12. No real system-audio transport, screen integration, production pairing, or UI.

### Automated tests

```powershell
pytest tests/unit/test_synthetic_audio.py tests/unit/test_audio_receive_buffer.py `
  tests/unit/test_audio_network_metrics.py tests/unit/test_codec_preference.py `
  tests/integration/test_webrtc_audio_local.py
# Optional real two-machine / speakers:
pytest -m network
pytest -m hardware
```

Normal `pytest` does not require speakers or two computers.

---

## Execution order

1. **Experiment A** first — foundation for VPN-safe networking.
2. **Experiment B** next — two-machine reachability before heavy media work.
3. **Experiment C** — local DXcam viability before WebRTC / Phase 1.
4. **Experiment D** — local WASAPI loopback viability.
5. **Experiment E** — synthetic WebRTC video / ICE host path.
6. **Experiment F** — synthetic WebRTC Opus audio / ICE host path.

## Go / no-go gate (from PLAN.md)

If Experiments **C**, **E**, and **F** meet rough latency/CPU bars for the
Balanced preset (`1280×720@30`), begin Phase 1 (screen-only prototype).
Otherwise keep the architecture but schedule a native capture/encode helper
spike before investing in full Phase 3 UI work.

## What belongs here later

When implemented, expect one script (or small pair of scripts) per experiment,
plus short result notes. Do **not** add application UI, signaling product code,
or packaging from this folder.
