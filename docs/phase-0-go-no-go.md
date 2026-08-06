# Phase 0 go / no-go review

**Product:** Snowlink  
**Scope:** Review only — Experiments A–F evidence against Phase 1 readiness  
**Review host date (UTC):** 2026-08-06  
**Decision:** `NO-GO`

---

## 1. Executive decision

**`NO-GO`**

Phase 1 (screen-only WebRTC prototype) must not begin yet. Ordinary automated quality checks pass, Experiment A is locally proven, and short local DXcam / WASAPI / in-process WebRTC smoke paths exist — but the Phase 0 minimum gate for **two-computer LAN reachability under VPN**, **Balanced capture sustainability**, and **two-computer synthetic VP8 (Experiment E)** is not met by repository evidence.

Do not treat “scripts exist” or “commands were run sometime” as passes. Recorded metrics under `experiment-results/` are sparse, incomplete, and in key cases fail the stated thresholds.

---

## 2. Test environment

Values below are from the **local review host** where this report was authored, plus dependency versions from the project venv. Computer B and several network fields are not documented in the repository.

| Item | Value |
| --- | --- |
| Computer A CPU | 11th Gen Intel Core i7-11800H @ 2.30 GHz |
| Computer A GPU | NVIDIA GeForce RTX 3050 Laptop GPU |
| Computer A RAM | 31.9 GB |
| Computer A Windows version | Windows 11 (build 26200 / DisplayVersion 25H2; `platform` reports `Windows-11-10.0.26200`) |
| Computer B CPU | NOT MEASURED |
| Computer B GPU | NOT MEASURED |
| Computer B RAM | NOT MEASURED |
| Computer B Windows version | NOT MEASURED (claimed Windows 11 in plan / prior task text only) |
| Wired or Wi-Fi connection | NOT MEASURED |
| LAN subnet | NOT MEASURED (docs use illustrative `192.168.1.0/24` examples only) |
| VPN products / sanitized labels | NOT MEASURED (generic “Allow LAN” guidance exists; no product-specific filled matrix) |
| Python version | 3.12.10 |
| aiortc version | 1.15.0 |
| PyAV (`av`) version | 17.1.0 |
| DXcam version | 0.3.0 |
| PyAudioWPatch version | 0.2.12.8 |

Sensitive data (VPN credentials, account names, public IPs) was not recorded.

---

## 3. Experiment summary

| Experiment | Status | Key evidence | Blocking issue |
| ---------- | ------ | ------------ | -------------- |
| A | PASS | Unit + local TCP echo integration tests; classification/selection fixtures; `ADDR_NOT_AVAILABLE` / `PORT_IN_USE` covered | None for Phase 1 **if** B later confirms cross-machine bind on physical LAN IPs |
| B | FAIL | Only one saved JSON: failed `CONNECTION_TIMEOUT` to `127.0.0.1:1` (not a LAN peer matrix). `docs/vpn-lan-access.md` result table is empty | No proven two-PC TCP matrix; both-VPN path undocumented with measurements |
| C | FAIL | Short DXGI/WinRT JSONs on one host; best Balanced-like FPS ≈ **21.6–21.7** over **3–5 s**, not ≥60 s / ≈30 FPS | Does not meet Balanced FPS or duration gate; Computer B missing |
| D | WARN | Hardware smoke: default WASAPI loopback endpoint present; synthetic pipeline unit/integration tests pass; **no** Experiment D benchmark JSON | Not a Phase 1 screen-only blocker, but Phase 2 audio readiness unproven |
| E | FAIL | In-process local `test_webrtc_video_local_loopback` passes; **no** `experiment-results/experiment-e/` two-machine / VPN / 10-minute JSON | Phase 1 dependency unmet |
| F | WARN | Local Opus preference + synthetic audio unit/integration tests; **no** Experiment F two-machine JSON | Phase 2 readiness unproven; not alone a Phase 1 blocker |

---

## 4. Experiment A review

### Intent

Adapter enumeration / classification, manual override, bind TCP to selected IPv4 only, clear errors, clean socket close.

### Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Physical LAN adapters identified | PASS (automated / fixture + Windows enumeration code) | `src/snowlink/platform_win/adapters.py` (`GetAdaptersAddresses`); `tests/unit/test_adapter_classification.py` prefers ethernet/wifi over VPN/virtual |
| VPN / virtual distinguished | PASS (automated) | Categories include `vpn_or_tunnel`, Hyper-V/WSL/Tailscale-style fixtures in `tests/fixtures/adapters.py` |
| Manual override | PASS (automated) | Selection helpers / CLI `--ip` path covered in unit tests and `experiments/experiment_a_adapter_bind.py` |
| TCP bind to exact selected IPv4 | PASS (local) | `tests/integration/test_tcp_echo_local.py` asserts `getsockname()` equals `127.0.0.1:<port>` (not `0.0.0.0`) |
| Invalid bind addresses understandable | PASS | Same file: TEST-NET bind → `ADDR_NOT_AVAILABLE` (or OS equivalents); occupied port → clear failure |
| Sockets close cleanly | PASS (local) | Echo server/client tests join and complete without hang |
| Cross-machine bind under VPN | INSUFFICIENT EVIDENCE | No Experiment A result JSON under `experiment-results/`; deferred to Experiment B |

**Verdict:** PASS for local/automated Phase 0 A capabilities. Cross-machine confirmation remains Experiment B’s job and is **not** evidenced.

---

## 5. Experiment B review

### Matrix

| Scenario | Result | Source IP | Destination IP | Connection time | Notes |
| --- | --- | --- | --- | --- | --- |
| VPN off/off | INSUFFICIENT EVIDENCE | NOT MEASURED | NOT MEASURED | NOT MEASURED | No success JSON in repo |
| VPN on/off | INSUFFICIENT EVIDENCE | NOT MEASURED | NOT MEASURED | NOT MEASURED | No success JSON in repo |
| VPN off/on | INSUFFICIENT EVIDENCE | NOT MEASURED | NOT MEASURED | NOT MEASURED | No success JSON in repo |
| VPN on/on | FAIL / not demonstrated | `null` (requested source not set) | `127.0.0.1:1` | connect ≈ 501 ms then timeout | Sole file: `experiment-results/experiment-b/2026-08-06T150739_vpn-on-on_client_bbd101aa-5c0f-49.json` — `success: false`, `CONNECTION_TIMEOUT`. Target is loopback port 1, **not** a physical LAN peer. Cannot be used as both-VPN LAN proof. |

### Both-VPN / Allow LAN

| Question | Finding |
| --- | --- |
| Both-VPN works on physical LAN IPs? | INSUFFICIENT EVIDENCE |
| Required “Allow LAN” (or equivalent)? | NOT MEASURED — `docs/vpn-lan-access.md` documents possible setting **names** and troubleshooting, but the §12 result template is **blank** (no filled product/setting outcome) |

**Verdict:** FAIL against Phase 0 gate (“Experiment B proves TCP connectivity between both computers”).

---

## 6. Experiment C review

### Available JSON (Computer A / review host only)

All files under `experiment-results/experiment-c/`. Native monitor in successful runs: **1920×1080** (`Generic PnP Monitor`, DXcam `0/0`). Computer B: **NOT MEASURED**.

#### Balanced target: 1280×720 @ 30 FPS

| Metric | DXGI `…161017…` (best short run) | DXGI `…160922…` | WinRT `…161046…` | DXGI cursor `…161042…` |
| --- | --- | --- | --- | --- |
| selected capture backend | dxgi | dxgi | winrt | dxgi |
| native monitor resolution | 1920×1080 | 1920×1080 | 1920×1080 | enumerated 1920×1080; capture not started |
| duration | **5 s** | **3 s** | **3 s** | 0 s (error) |
| actual capture FPS | **21.637** | 0.3295 (1 frame / many nulls) | **21.7026** | 0 |
| actual preview FPS | 21.637 (`show_preview: false`; render FPS = consume path) | 0.3295 | 21.7026 | 0 |
| dropped / overwritten frames | overwritten 0; null 0 | null 65; overwritten 0 | null 0; overwritten 0 | n/a |
| average frame age | 2.00 ms | 1.27 ms | 2.26 ms | NOT MEASURED |
| p95 frame age | 2.78 ms | 1.27 ms | 3.18 ms | NOT MEASURED |
| average CPU | 62.9% | 11.6% | 62.9% | 99.9% (error path) |
| peak CPU | 237.5% | 75.0% | 118.8% | 99.9% |
| memory start / end / peak (MB) | 24.4 / 103.8 / 103.8 | 23.9 / 91.5 / 94.1 | 24.0 / 111.1 / 117.1 | 24.2 / 64.7 / 64.7 |
| shutdown behavior | `success: true` on short runs (errors empty) | same | same | clean fail with structured error |
| cursor support | NOT MEASURED (not requested) | not requested | not requested | **FAIL as expected:** `UNSUPPORTED_CURSOR_CAPTURE` |

### Low / High presets

| Preset | Result |
| --- | --- |
| Low `854×480@15` | NOT MEASURED (no suite JSON) |
| High `1920×1080@30` | NOT MEASURED (no suite JSON) |

### Gate checks

| Gate | Status |
| --- | --- |
| Continuous ≥ 60 s Balanced | **FAIL** — longest recorded run is 5 s |
| Actual FPS within ~10% of 30 (≈27–33) under light activity | **FAIL** — ≈21.6–21.7 FPS on successful short runs |
| No continuously growing memory | INSUFFICIENT EVIDENCE over 60 s; short runs show startup rise then flat peak≈end, which is **not** a 60 s soak |

### Initial Phase 1 backend recommendation (provisional)

- **DXGI** remains the planned default and is the only backend with a clear cursor-unsupported diagnostic.
- WinRT short-run FPS was similar (~21.7) on this host; **neither** backend met the 30 FPS ±10% bar in recorded data.
- Cursor compositing: use WinRT only if Phase 1 requires cursor; DXGI correctly refuses `--show-cursor`.

**Verdict:** FAIL for Phase 1 gate.

**Additional positive smoke (not a substitute for Balanced gate):** `pytest -m hardware` → `test_real_dxcam_grab_optional` PASSED (single-frame DXGI grab).

---

## 7. Experiment D review

| Item | Computer A | Computer B |
| --- | --- | --- |
| loopback endpoint detected | PASS (smoke): default WASAPI loopback has ≥1 input channel (`test_real_loopback_optional`) | NOT MEASURED |
| native sample rate | NOT MEASURED | NOT MEASURED |
| native channels | NOT MEASURED | NOT MEASURED |
| target conversion format | Designed 48 kHz / stereo / 20 ms (code + synthetic tests) | NOT MEASURED |
| captured non-silent frames | NOT MEASURED (no live benchmark JSON) | NOT MEASURED |
| underruns / overruns / dropped samples | NOT MEASURED live; synthetic tests exercise counters | NOT MEASURED |
| average / peak buffer fill | NOT MEASURED | NOT MEASURED |
| CPU / memory | NOT MEASURED | NOT MEASURED |
| clean shutdown | PASS in synthetic pipeline tests | NOT MEASURED |

**Phase 2 readiness:** **Not ready** — implementation exists; live 60 s non-silent loopback benchmarks are missing.

**Blocks Phase 1 screen-only?** No (audio is Phase 2), unless treated as a broader “Phase 0 incomplete” process risk — which it is, but not a screen-path architectural showstopper by itself.

---

## 8. Experiment E review

### Both VPNs on (required gate)

| Metric | Result |
| --- | --- |
| signaling success | NOT MEASURED (two-machine) |
| ICE state | NOT MEASURED (two-machine) |
| peer connection state | NOT MEASURED (two-machine) |
| selected local / remote candidate | NOT MEASURED |
| physical LAN IP pair selected | NOT MEASURED |
| codec | Local in-process test prefers VP8; two-machine codec confirmation NOT MEASURED |
| requested / received / rendered FPS | NOT MEASURED (two-machine) |
| packets lost / jitter / RTT / bitrate | NOT MEASURED |
| sender / receiver CPU | NOT MEASURED |
| memory growth | NOT MEASURED |
| ten-minute test | NOT MEASURED — **no** `experiment-results/experiment-e/` artifacts |
| clean shutdown | PASS for local in-process peers + signaling-only shutdown test |

### Local (same-process) evidence only

- `tests/integration/test_webrtc_video_local.py::test_webrtc_video_local_loopback` — ICE connects; ≥5 synthetic frames received; latest-frame slot depth ≤1; peers close.
- Host-ICE policy in code: `host_only_configuration()` (no STUN/TURN) in `src/snowlink/rtc/peer_connection.py`.

**Verdict:** FAIL Phase 1 gate — synthetic VP8 is **not** evidenced as reliable between the two target computers with both VPNs on, nor for a ten-minute soak.

---

## 9. Experiment F review

### Both VPNs on

| Metric | Result |
| --- | --- |
| Opus selected | Local unit/preference tests; two-machine NOT MEASURED |
| ICE state / selected candidate pair | NOT MEASURED |
| received sample rate / channels / frame size | NOT MEASURED (two-machine) |
| invalid PTS count | NOT MEASURED live |
| estimated tone frequency | NOT MEASURED live |
| underruns / overruns | NOT MEASURED live |
| packet loss / jitter / RTT | NOT MEASURED |
| memory growth / ten-minute / clean shutdown | Ten-minute NOT MEASURED; local unit/integration shutdown paths exist |

**Verdict:** WARN — Phase 2 readiness **not** demonstrated. Does not alone force Phase 1 `NO-GO`, but Phase 0 completion criteria in `PLAN.md` (“A–F documented results on both target PCs”) remain unmet.

---

## 10. Automated quality checks

Commands run on the review host (2026-08-06):

```powershell
pytest
ruff check .
mypy src
```

| Check | Result |
| --- | --- |
| `pytest` | **164 passed**, 0 failed, **0 skipped** reported in default run (~8.1 s) |
| `ruff check .` | **All checks passed** (exit 0) |
| `mypy src` | **Success: no issues found in 46 source files** (exit 0) |

### Notes

- Optional markers: `hardware` (2 tests) and `network` (0 collected). Hardware smokes were also re-run explicitly: **2 passed**.
- No `pytest` warnings affecting runtime were reported in the default summary.
- Automated tests **must not** be treated as substitutes for missing two-machine Experiment B/E JSON.

**Gate impact:** Automated quality is **green**. Decision remains `NO-GO` solely because **manual/network/hardware measurement gates** for B/C/E fail or lack evidence — not because unit tests failed.

---

## 11. Phase 0 minimum gate criteria

### Required for Phase 1

| Criterion | Status |
| --- | --- |
| Experiment A passes | **Met** (local/automated) |
| Experiment B proves TCP between both computers | **Not met** |
| Both-VPN works **or** exact Allow-LAN condition documented with evidence | **Not met** |
| Experiment C Balanced continuous ≥ 60 s | **Not met** |
| Experiment C actual FPS ≈ within 10% of 30 | **Not met** (≈21.6 FPS recorded) |
| Experiment C no continuously growing memory | **Insufficient** (no 60 s soak) |
| Experiment E synthetic VP8 between computers | **Not met** |
| Experiment E both VPNs under documented config | **Not met** |
| Selected ICE pair uses intended physical LAN (or documented acceptable path) | **Not met** |
| Experiment E no growing video latency | **Not met** / NOT MEASURED |
| Experiment E ten-minute run without crash / continuous memory growth | **Not met** |
| Ordinary automated tests pass | **Met** |
| Ruff passes | **Met** |
| Mypy passes | **Met** |
| Shutdown leaves no known leaked resources | **Partially met** in automated local tests; two-machine media shutdown NOT MEASURED |

### Required later for Phase 2

| Criterion | Status |
| --- | --- |
| Experiment D non-silent system audio | NOT MEASURED |
| Experiment F valid Opus transport | NOT MEASURED (two-machine) |
| Audio timestamps continuous | Code intent + unit tests; live NOT MEASURED |
| Receiver buffering bounded | Code + unit tests; live NOT MEASURED |

---

## 12. Blocking issues

| # | Issue | Severity | Experiment | Evidence | Likely cause | Recommended action | Blocks Phase 1? | Owner / next task |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | No proven two-PC TCP matrix (including vpn-on-on) | **Critical** | B | Empty matrix; only failed `127.0.0.1:1` JSON; blank `docs/vpn-lan-access.md` results | Results never archived / wrong target used / tests not run on LAN | Re-run Experiment B four scenarios on real physical LAN IPs; fill matrix; document Allow-LAN if required | **Yes** | Operator: complete B runbook; archive JSON under `experiment-results/experiment-b/` |
| 2 | No two-machine Experiment E (VPN-on) / no 10-minute soak | **Critical** | E | No `experiment-results/experiment-e/` | Manual E results not present in repo | After B passes, run E vpn-on-on ≥120 s then 600 s; confirm LAN ICE pair | **Yes** | Operator + keep E CLI as-is |
| 3 | Balanced capture below FPS/duration gate | **Critical** | C | DXGI/WinRT ≈21.6 FPS; max duration 5 s | Desktop idle/null-frame behavior, short benchmarks, and/or capture scheduling not sustaining 30 FPS | Re-run `--duration 60` Balanced with light activity; investigate null/low FPS; compare DXGI vs WinRT; only then decide backend | **Yes** | Operator: 60 s suite on **both** PCs; engineer: analyze if still <27 FPS |
| 4 | Computer B hardware / results absent | **High** | A–F | Environment table | Dual-PC artifacts not copied into this workspace | Collect Computer B env + JSON into `experiment-results/` | **Yes** (process) | Operator |
| 5 | Experiment D live benchmarks missing | **Medium** | D | No `experiment-d` JSON | Not archived / not run for gate | Run 60 s loopback with non-DRM audio before Phase 2 | No (Phase 1) | Operator before Phase 2 |
| 6 | Experiment F two-machine missing | **Medium** | F | No `experiment-f` JSON | Not archived / not run | After E path proven, run F vpn-on-on + optional 10 min | No (Phase 1) | Operator before Phase 2 |
| 7 | DXGI cursor unsupported | **Low** | C | `UNSUPPORTED_CURSOR_CAPTURE` JSON | DXcam DXGI limitation | Phase 1: no cursor on DXGI, or WinRT if cursor required | No | Document as Phase 1 constraint when GO |
| 8 | Misleading `vpn-on-on` filename on non-LAN failure | **Low** | B | JSON remote `127.0.0.1:1` | Accidental/local probe saved under session name | Delete or quarantine; never count as LAN evidence | No (hygiene) | Operator |

---

## 13. Phase 1 constraints

**N/A — decision is `NO-GO`.**

No Phase 1 constraints checklist is authorized until B, C (Balanced 60 s / FPS), and E (two-machine VPN path + 10-minute) are re-measured and this review is updated.

Provisional notes for the **future** GO (not authorization to start Phase 1):

- Expect Balanced-first defaults (`1280×720@30`) only after FPS gate is actually met.
- DXGI likely remains initial backend unless WinRT wins a fair 60 s comparison.
- Host-ICE / bind-to-selected-LAN-IP / manual IP connection remain architectural intent.
- No audio, pairing, or production signaling in Phase 1 (unchanged plan).

---

## 14. Selected Phase 1 technical choices

**Not finalized** — blocked by `NO-GO`. Evidence-based provisional recommendations only:

| Choice | Provisional recommendation | Basis |
| --- | --- | --- |
| initial screen-capture backend | DXGI (tentative) | Planned default; WinRT not shown superior in short runs; cursor needs WinRT |
| default resolution | 1280×720 | Plan Balanced; **not yet validated at ≥27 FPS for 60 s** |
| default FPS | 30 (target) | Plan; **recorded ~22 FPS must be fixed or target lowered with explicit plan change** |
| initial codec | VP8 | Local E tests + plan; two-machine unproven |
| signaling port | 3847 TCP (signaling) / experiment E used 3848 | Plan default 3847; confirm free on both PCs during B/E |
| ICE policy | Host-only (no STUN/TURN) | `host_only_configuration()` |
| sender queue strategy | Latest-frame / depth 1 | Experiment C/E design |
| receiver queue strategy | Latest-frame / depth 1 | Experiment E consumer |
| preview implementation for Phase 1 | OpenCV or simple Qt viewer (not decided by Phase 0 metrics) | Insufficient product-UI evidence; plan says PySide6 later |
| candidate filtering needed? | **Likely yes** if VPN hosts appear — **NOT MEASURED** on real VPN ICE | E diagnostics exist; need vpn-on-on selected-pair evidence |
| avoid private aiortc/aioice APIs? | Yes, prefer public RTCConfiguration / transceiver codec prefs already used | Current E/F code path |

Do **not** preserve “Balanced @ 30 works” as a fact — recorded C results contradict it until re-measured.

---

## 15. Phase 1 readiness checklist

```text
[ ] Repository clean
[x] Tests pass
[x] Ruff passes
[x] Mypy passes
[x] Experiment A pass
[ ] Experiment B pass
[ ] Experiment C pass
[ ] Experiment E pass
[ ] VPN-on path confirmed
[ ] Selected ICE pair confirmed
[ ] No blocking memory growth
[ ] Clean shutdown confirmed
[ ] Phase 1 constraints documented
```

Notes on checked items:

- Automated A / pytest / ruff / mypy are evidenced on the review host.
- “Clean shutdown confirmed” is **not** checked at checklist level because two-machine media shutdown is unproven (local-only evidence exists).
- Repository clean is unchecked (working tree contains untracked experiment/media/rtc work and caches per status at review time).

---

## 16. Recommendation

* **Final decision:** `NO-GO`
* **Concise reason:** Critical Phase 1 dependencies — proven LAN TCP under VPN (B), Balanced DXcam sustainability (C), and two-computer synthetic VP8 with LAN ICE / 10-minute stability (E) — lack acceptable recorded evidence; available C metrics miss the FPS/duration bars.
* **Unresolved risks:** VPN kill-switch / Allow-LAN unknown; ICE may prefer VPN adapters; capture may remain ~22 FPS; Computer B unknown; D/F unproven for Phase 2.
* **Exact next task (highest-priority blocker):**

```text
Re-run and archive Experiment B on both target PCs for all four VPN scenarios using physical LAN IPs (fill docs/vpn-lan-access.md results), then re-run Experiment C Balanced 1280×720@30 for ≥60 seconds on each PC, then Experiment E vpn-on-on with LAN ICE confirmation and a ten-minute soak. Do not begin Phase 1 until those JSON results pass the Phase 0 gates.
```

---

## Evidence inventory (paths)

| Path | Role |
| --- | --- |
| `experiment-results/experiment-b/2026-08-06T150739_vpn-on-on_client_bbd101aa-5c0f-49.json` | Non-LAN timeout only |
| `experiment-results/experiment-c/2026-08-06T160922_monitor-0_dxgi_1280x720.json` | 3 s DXGI (poor FPS) |
| `experiment-results/experiment-c/2026-08-06T161017_monitor-0_dxgi_1280x720.json` | 5 s DXGI ≈21.6 FPS |
| `experiment-results/experiment-c/2026-08-06T161042_monitor-0_dxgi_1280x720.json` | Cursor unsupported |
| `experiment-results/experiment-c/2026-08-06T161046_monitor-0_winrt_1280x720.json` | 3 s WinRT ≈21.7 FPS |
| `docs/vpn-lan-access.md` | Guidance; blank measured matrix |
| `experiments/README.md` | Experiment instructions |
| Automated: `pytest` / `ruff` / `mypy` | Green |

Missing directories (expected when experiments are properly archived): `experiment-results/experiment-a/`, `experiment-d/`, `experiment-e/`, `experiment-f/`, plus complete B matrix and C 60 s suite on both PCs.
