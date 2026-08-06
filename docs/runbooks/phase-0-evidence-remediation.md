# Phase 0 evidence remediation runbook

**Scope:** Collect missing manual Experiment B and Experiment C evidence only.  
**Do not** start Phase 1.  
**Do not** change `docs/phase-0-go-no-go.md` to `GO` until Experiments B, C, and E all have sufficient real evidence.

This runbook uses the CLI options that exist in the repository today.

---

## 1. Goal (Experiment B)

Archive one **client** JSON result for each VPN scenario under:

```text
experiment-results/experiment-b/
```

Required `--session-name` values:

| Session name  | Computer A VPN | Computer B VPN |
| ------------- | -------------- | -------------- |
| `vpn-off-off` | Off            | Off            |
| `vpn-on-off`  | On             | Off            |
| `vpn-off-on`  | Off            | On             |
| `vpn-on-on`   | On             | On             |

Computer A runs the diagnostic TCP **server** bound to its physical LAN IPv4.  
Computer B runs the diagnostic TCP **client** and binds to its physical LAN IPv4 with `--source-ip`.

Do **not** use:

* `127.0.0.1` / `localhost`
* public IP addresses
* VPN adapter addresses (unless intentionally documenting a fallback)
* `0.0.0.0` as Computer A’s selected bind address

---

## 2. Repository entry points (verified)

| Role | Path |
| --- | --- |
| Experiment B CLI | `experiments/experiment_b_two_machine_tcp.py` |
| Adapter listing (Experiment A) | `experiments/experiment_a_adapter_bind.py` |
| Evidence validator | `scripts/dev/validate_phase0_evidence.py` |
| Default result directory | `experiment-results/experiment-b/` (gitignored) |
| Default TCP port | `3847` |

Experiment B subcommands: `guide`, `serve`, `connect`, `summarize`.

Relevant flags:

* `--session-name` — required for `serve` / `connect`
* `--ip` — bind IP (`serve`) or remote Computer A IP (`connect`)
* `--source-ip` — client local bind before connect
* `--port` — default `3847`
* `--timeout` — seconds (default `5`)
* `--serve-forever` — keep accepting clients until Ctrl+C
* `--results-dir` — JSON output directory
* `--json` — machine-readable stdout (results are still written to disk)

---

## 3. One-time setup on both computers

1. Open PowerShell in the Snowlink repo root.
2. Activate the project venv.
3. Confirm dependencies are installed (`pip install -r requirements-dev.txt` as needed).
4. Confirm both PCs are on the same physical LAN (or otherwise routable local subnet).

Printed instructions anytime:

```powershell
python experiments/experiment_b_two_machine_tcp.py guide
```

---

## 4. Preliminary checks (before every scenario)

On **each** computer:

```powershell
python experiments/experiment_a_adapter_bind.py list
```

Verify the candidate IPv4:

* Assigned to **physical Ethernet or Wi-Fi** (preferred / `physical_ethernet` / `physical_wifi`)
* Private LAN IPv4 (`10.0.0.0/8`, `172.16.0.0/12`, or `192.168.0.0/16`)
* **Not** loopback (`127.0.0.0/8`)
* **Not** the VPN / tunnel / Hyper-V / WSL interface
* Both computers remain on the same LAN or a routable local subnet

Record placeholders used below:

```text
<COMPUTER_A_LAN_IP>
<COMPUTER_B_LAN_IP>
```

Example shape only (do not copy these addresses unless they match `list`):

```text
<COMPUTER_A_LAN_IP> = 192.168.1.25
<COMPUTER_B_LAN_IP> = 192.168.1.30
```

---

## 5. Windows Firewall behavior

* Computer A’s `serve` process must remain running while Computer B runs `connect`.
* Windows may show a firewall prompt the first time Python listens — choose **Private** network access if you intend LAN testing.
* Snowlink **does not** disable or reconfigure Windows Firewall automatically.
* A **timeout** may indicate Firewall block, VPN LAN blocking, wrong IP, inactive server, or another silent drop. Do **not** treat a timeout as proof of one specific cause.
* A **refusal** usually means the destination was reachable but nothing was accepting on that IP:port (server not listening, wrong bind IP, or active refuse).

---

## 6. How to run one scenario (pattern)

1. Set the VPN states for that scenario on both PCs.
2. On each PC, re-run `list` and confirm LAN IPs still match the placeholders.
3. Start Computer A `serve` with the matching `--session-name` and `--serve-forever`.
4. Confirm Computer A prints `Listening on <COMPUTER_A_LAN_IP>:3847 (getsockname)`.
5. On Computer B, run `connect` with the same `--session-name` and `--source-ip <COMPUTER_B_LAN_IP>`.
6. Keep the JSON path printed by the client (`result file: ...`).
7. Stop Computer A with Ctrl+C when finished with that scenario (or leave it up if retesting).

Client results are the matrix evidence. Server JSON is helpful but not required for the validator.

---

## 7. Scenario commands

Replace placeholders with the physical LAN IPv4s from `list`.

### 7.1 `vpn-off-off`

**VPN state:** Computer A Off, Computer B Off.

Computer A:

```powershell
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-off-off `
  --serve-forever
```

Computer B:

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-off-off `
  --source-ip <COMPUTER_B_LAN_IP> `
  --timeout 5
```

**Expected success output (Computer B):**

```text
Connect OK — echo verified
  session:     vpn-off-off
  ...
  source:      <COMPUTER_B_LAN_IP>:...
  destination: <COMPUTER_A_LAN_IP>:3847
  result file: experiment-results\experiment-b\<timestamp>_vpn-off-off_client_<id>.json
```

**Expected JSON location:** `experiment-results/experiment-b/*_vpn-off-off_client_*.json`

**If it fails:** leave the printed error / `Result file:` path; note firewall prompts, VPN state, and whether Computer A still showed `Listening on ...`. Do not delete the failure JSON.

---

### 7.2 `vpn-on-off`

**VPN state:** Computer A On, Computer B Off. Re-run `list` on Computer A after enabling VPN and confirm `<COMPUTER_A_LAN_IP>` is still the physical LAN address (not the VPN address).

Computer A:

```powershell
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-on-off `
  --serve-forever
```

Computer B:

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-on-off `
  --source-ip <COMPUTER_B_LAN_IP> `
  --timeout 5
```

**Expected JSON location:** `experiment-results/experiment-b/*_vpn-on-off_client_*.json`

**If it fails:** keep the client JSON; record likely Firewall / VPN “Allow LAN” / wrong-IP notes. A timeout alone does not prove one cause.

---

### 7.3 `vpn-off-on`

**VPN state:** Computer A Off, Computer B On. Re-run `list` on Computer B and confirm `<COMPUTER_B_LAN_IP>` is still the physical LAN address before using `--source-ip`.

Computer A:

```powershell
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-off-on `
  --serve-forever
```

Computer B:

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-off-on `
  --source-ip <COMPUTER_B_LAN_IP> `
  --timeout 5
```

**Expected JSON location:** `experiment-results/experiment-b/*_vpn-off-on_client_*.json`

**If it fails:** archive the client JSON; confirm Computer B did not source from the VPN IP (`actual_source_ip` in JSON).

---

### 7.4 `vpn-on-on`

**VPN state:** Computer A On, Computer B On. Re-run `list` on **both** PCs and confirm both placeholders still refer to physical LAN IPv4s.

Computer A:

```powershell
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-on-on `
  --serve-forever
```

Computer B:

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-on-on `
  --source-ip <COMPUTER_B_LAN_IP> `
  --timeout 5
```

**Expected JSON location:** `experiment-results/experiment-b/*_vpn-on-on_client_*.json`

**If it fails:** keep the JSON. Document whether VPN “Allow LAN access” / equivalent was available. Do not disable managed VPN protections.

---

## 8. What each client JSON already records

Successful and failed `connect` runs write JSON via the existing Experiment B result writer. Fields include:

* `session_name`
* `success`
* `local.requested_source_ip`
* `local.actual_source_ip` / `actual_source_port` (from `getsockname()`)
* `local.adapter_name` / `adapter_category` when enumeration succeeds
* `remote.ip` / `remote.port`
* `timing_ms.connect` / `timing_ms.echo_round_trip` / `timing_ms.total`
* `error` (structured) on failure
* `started_at_utc` / `completed_at_utc`

Optional machine-readable stdout:

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip <COMPUTER_A_LAN_IP> `
  --port 3847 `
  --session-name vpn-off-off `
  --source-ip <COMPUTER_B_LAN_IP> `
  --timeout 5 `
  --json
```

Copy client JSON from Computer B into the same repo path on the review host if results live on separate machines.

---

## 9. Summarize and validate Experiment B evidence

Human-readable table of archived client results:

```powershell
python experiments/experiment_b_two_machine_tcp.py summarize `
  --results-dir experiment-results/experiment-b
```

Matrix gate check (PASS / FAIL / MISSING / INVALID). Loopback-only files are **INVALID** and never counted as two-computer PASS:

```powershell
python scripts/dev/validate_phase0_evidence.py --experiment b
```

Optional explicit directory:

```powershell
python scripts/dev/validate_phase0_evidence.py --experiment b `
  --results-dir experiment-results/experiment-b
```

Exit code `0` only when all four scenarios are **PASS**.

Also fill the manual matrix in `docs/vpn-lan-access.md` §12 when runs complete.

---

## 10. After Experiment B

1. Keep all real client JSON under `experiment-results/experiment-b/`.
2. Do **not** mark Phase 0 `GO` yet.
3. Do **not** invent a passing `experiment-results/phase-0-summary.json` until Experiments **B, C, and E** all have sufficient real evidence.
4. Continue with Experiment C below, then later Experiment E.

---

## 11. Goal (Experiment C)

Archive one **Balanced** DXcam benchmark JSON (≥60 s, 1280×720 @ 30 FPS) on **each** target Windows 11 computer under:

```text
experiment-results/experiment-c/
```

That directory is gitignored. Use distinct `--machine-label` values:

| Label | Computer |
| --- | --- |
| `computer-a` | First target PC |
| `computer-b` | Second target PC |

Do **not** store usernames, public IP addresses, VPN credentials, or screen contents.

Phase 0 report provisional backend: **DXGI** (`--backend dxgi`). Benchmark DXGI first. Use WinRT only when `list` shows it available and you need a comparison or cursor support.

A 3–5 second smoke test does **not** count as final evidence.

---

## 12. Experiment C entry points (verified)

| Role | Path |
| --- | --- |
| Experiment C CLI | `experiments/experiment_c_screen_capture.py` |
| Evidence validator | `scripts/dev/validate_phase0_evidence.py --experiment c` |
| Default result directory | `experiment-results/experiment-c/` (gitignored) |

Subcommands: `list`, `preview`, `benchmark`, `suite`.

Relevant flags (as implemented):

* `--monitor` — logical monitor index (default `0`)
* `--backend` — `dxgi` (default) or `winrt`
* `--fps` / `--width` / `--height` — defaults match Balanced `30` / `1280` / `720`
* `--duration` — seconds (benchmark default `60`)
* `--preset balanced` — optional; overrides fps/width/height to Balanced
* `--no-preview` — benchmark without OpenCV window (still scales for metrics)
* `--machine-label` — `computer-a` / `computer-b` (sanitized into JSON + filename)
* `--results-dir` — JSON output directory
* `--json` — also print result JSON to stdout (files still written for `benchmark`)

Capture extras (optional): `--show-cursor` (WinRT only in DXcam).

---

## 13. Experiment C one-time setup

1. Open PowerShell in the Snowlink repo root on the target PC.
2. Activate the project venv.
3. Install capture extras if needed:

```powershell
pip install -e ".[dev,capture]"
```

---

## 14. List monitors and backends

On **each** computer:

```powershell
python experiments/experiment_c_screen_capture.py list
```

Optional machine-readable output:

```powershell
python experiments/experiment_c_screen_capture.py list --json
```

Verify before benchmarking:

* Intended `--monitor` index
* Monitor resolution (native width/height)
* Backend availability (`dxgi` / `winrt`)
* Primary vs secondary monitor status
* Mapped DXcam `device_idx` / `output_idx` (do **not** assume `--monitor` equals DXcam `output_idx`)
* No invalid monitor mapping

Record:

```text
<MONITOR_INDEX>
```

Example: `<MONITOR_INDEX> = 0` for the primary display.

---

## 15. Optional preview check

Short visual validation only — **not** final evidence:

```powershell
python experiments/experiment_c_screen_capture.py preview `
  --monitor <MONITOR_INDEX> `
  --backend dxgi `
  --fps 30 `
  --width 1280 `
  --height 720
```

Press Esc or close the preview window to stop. Confirm the intended monitor contents appear.

---

## 16. Required 60-second Balanced benchmark

Use light desktop activity (not idle black desktop if that collapses FPS). Keep the process running until it finishes and prints `result_file=...`.

### 16.1 Computer A

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor <MONITOR_INDEX> `
  --backend dxgi `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --duration 60 `
  --no-preview `
  --machine-label computer-a `
  --json
```

Equivalent with preset:

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor <MONITOR_INDEX> `
  --backend dxgi `
  --preset balanced `
  --duration 60 `
  --no-preview `
  --machine-label computer-a `
  --json
```

### 16.2 Computer B

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor <MONITOR_INDEX> `
  --backend dxgi `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --duration 60 `
  --no-preview `
  --machine-label computer-b `
  --json
```

**Expected JSON location (examples):**

```text
experiment-results/experiment-c/<timestamp>_computer-a_monitor-0_dxgi_1280x720.json
experiment-results/experiment-c/<timestamp>_computer-b_monitor-0_dxgi_1280x720.json
```

(With `--preset balanced`, the filename uses `balanced` instead of `1280x720`.)

If WinRT is available and DXGI fails or needs comparison:

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor <MONITOR_INDEX> `
  --backend winrt `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --duration 60 `
  --no-preview `
  --machine-label computer-a `
  --json
```

Copy JSON from each PC into the same `experiment-results/experiment-c/` folder on the review host when validating centrally.

---

## 17. Optional longer soak (recommended)

When memory growth or dropped-frame behavior is uncertain, run 5 minutes:

```powershell
python experiments/experiment_c_screen_capture.py benchmark `
  --monitor <MONITOR_INDEX> `
  --backend dxgi `
  --fps 30 `
  --width 1280 `
  --height 720 `
  --duration 300 `
  --no-preview `
  --machine-label computer-a `
  --json
```

Repeat on Computer B with `--machine-label computer-b`.

---

## 18. Experiment C pass / warn / fail rules

Mark a target computer **PASS** only when:

1. Capture initializes successfully.
2. The intended monitor is captured.
3. The benchmark lasts at least 60 seconds.
4. Requested FPS is 30 (1280×720 Balanced).
5. Actual capture FPS is approximately **27 FPS or higher** under light desktop activity.
6. Memory does not continuously grow during the test.
7. Capture resources stop cleanly.
8. No persistent capture errors occur.
9. Result JSON is written successfully.

Use **WARN** when:

* Actual FPS is below 27 but stable
* High CPU is recorded
* Dropped frames occur without growing latency
* Cursor support is missing (when cursor was requested)
* Only one backend works (operator note; single-file auto-check may still PASS/WARN on FPS)

Use **FAIL** when:

* Capture cannot run for 60 seconds
* Actual FPS is severely below target
* Memory continuously grows
* Capture freezes / persistent errors
* Monitor selection is incorrect
* DXcam resources do not close
* Result evidence is missing or invalid

Do **not** automatically fail only because some frames are dropped — evaluate whether latency / queue age grows.

---

## 19. Validate Experiment C evidence

```powershell
python scripts/dev/validate_phase0_evidence.py --experiment c
```

Optional explicit directory:

```powershell
python scripts/dev/validate_phase0_evidence.py --experiment c `
  --results-dir experiment-results/experiment-c
```

The validator:

* Searches `experiment-results/experiment-c/`
* Selects the newest Balanced ≥60 s result per `computer-a` / `computer-b`
* Rejects short runs, wrong resolution/FPS, synthetic/mocked markers, and bad schemas
* Prints status, duration, actual FPS, memory growth, and shutdown
* Exit code `0` only when **both** computers have sufficient evidence (`PASS` or `WARN`)

Example summary shape:

```text
Computer     Status   Duration   Actual FPS   Memory Growth   Shutdown
computer-a   PASS     60.2 s     29.4 FPS     +4.8 MB         clean
computer-b   WARN     60.1 s     26.3 FPS     +6.2 MB         clean
```

---

## 20. After Experiments B and C

1. Keep real JSON under `experiment-results/experiment-b/` and `experiment-results/experiment-c/`.
2. Do **not** mark Phase 0 `GO` yet.
3. Do **not** invent a passing `experiment-results/phase-0-summary.json` until Experiment **E** also has sufficient real evidence.
4. Next remediation target: Experiment E — two-computer VPN-on path + ten-minute soak.

---

## Related docs

* `docs/vpn-lan-access.md` — VPN / Firewall interpretation
* `docs/phase-0-go-no-go.md` — current `NO-GO` decision (do not flip here)
* `experiments/README.md` — Experiment B / C command summary
