# MVP ship evidence

**Date:** 2026-08-09  
**Scope:** Finish Snowlink MVP to product (Phases 0–4 code + packaging gate + polish)  
**Build:** `packaging/dist/Snowlink/Snowlink.exe` (PyInstaller onedir)  
**Portable zip:** `packaging/dist/Snowlink-MVP-portable.zip` (~336 MB, 2026-08-09)

Authority for open/closed rows: [`ship-checklist.md`](ship-checklist.md). This file must not mark a checklist item done unless the checklist does.

---

## Automated verification (this host)

| Check | Result |
|---|---|
| Full pytest (unit+protocol+integration) | **PASS** — 256 passed (2026-08-09) |
| Signaling reconnect unit tests | **PASS** — `tests/unit/test_signaling_reconnect.py` |
| Local Share/View integration + slot-taken | **PASS** — 3 passed |
| Soak sampler smoke (`scripts/dev/soak_sample.py --duration-s 3`) | **PASS** — `experiment-results/soak-smoke-2026-08-09.jsonl` |
| PyInstaller rebuild (`scripts/dev/build_gui_exe.py`) | **PASS** — 2026-08-09 |
| Local `Snowlink.exe` launch (5 s, no crash) | **PASS** — PID started and stopped cleanly |
| Portable zip refresh | **PASS** — `packaging/dist/Snowlink-MVP-portable.zip` |

---

## Ship checklist (`docs/runbooks/ship-checklist.md`)

- [x] Build onedir via `python scripts/dev/build_gui_exe.py`
- [x] Launch `Snowlink.exe` without a Python venv (local host smoke)
- [x] Clean Win11 VM: Home / Share / View / Diagnostics / Settings navigate
- [x] Clean Win11 VM: Diagnostics Connectivity checklist
- [x] Two-PC Share → View with pairing Approve
- [x] First-listen Windows Firewall prompt accepted (or documented manual rule)
- [x] VC++ redistributable dialog path verified on a PyAV-less clean VM

**Same-machine soak sample (supplemental):** CLI Share→View on `127.0.0.1:19875` with pairing code (video-only, auto-approve) ran ~29 minutes. Clean-VM / two-PC checklist rows above are closed by operator runs. Integration tests also cover local Share/View + second-viewer rejection.

---

## Acceptance / soak (`docs/runbooks/mvp-acceptance.md`)

### Functional §2.1

Use Share (★ preferred physical adapter + Bind IPv4) → pairing → View Connect → Approve.

- [x] Items 1–8 on two Win11 PCs
- [x] Interrupt recovery (~10 s link drop → `reconnecting` or clean fail + retry)
- [x] VPN-on path with Allow LAN (`docs/vpn-lan-access.md`)

### Latency (experimental)

| Metric | Target | Result |
|---|---|---|
| Glass-to-glass video (Low/Balanced, wired) | 80–200 ms | **PASS** — operator validated within target (wired LAN) |
| Audio latency (wired) | 40–120 ms | **PASS** — operator validated within target (wired LAN) |

### Soak harness

```powershell
# During an active Share or View session, attach to Snowlink.exe PID:
python scripts/dev/soak_sample.py --pid <PID> --duration-s 1800 --interval-s 30 --out soak-30m.jsonl
python scripts/dev/soak_sample.py --pid <PID> --duration-s 7200 --interval-s 60 --out soak-2h.jsonl
python scripts/dev/soak_sample.py --pid <PID> --duration-s 28800 --interval-s 60 --out soak-8h.jsonl
```

Live Share/View stats panel shows **CPU** and **RSS** for in-session observation.

| Duration | Status | Notes |
|---|---|---|
| Sampler smoke (3 s) | **PASS** | `experiment-results/soak-smoke-2026-08-09.jsonl` |
| ~29 min local Share→View (127.0.0.1, video-only, low preset) | **PASS** | `experiment-results/soak-30m-2026-08-09.jsonl` — 59 samples; no crash; RSS 176.6 → 241.6 MB (+65 MB); avg CPU ~61%. Superseded by operator 2 h / 8 h two-PC soaks below. |
| 2 h | **PASS** | Operator two-PC soak; `av_skew_ms` within ~100 ms / resync drops acceptable; no crash |
| 8 h | **PASS** | Operator two-PC soak; memory growth within &lt; 50–100 MB after warmup; no unbounded climb |

---

## Product polish (2026-08-09)

1. Reconciled `ship-checklist.md` ↔ this evidence file (no conflicting `[x]`)  
2. Home MVP copy; Diagnostics nav label; portable README quickstart; `LICENSE` (proprietary)  
3. High preset labeled **experimental** in Share/Settings  
4. Share selectors locked while session active  
5. Experiment E / lab default port aligned to **3847**  
6. Soak sampler writes summary if target PID exits mid-run  

---

## §17 sign-off status

| Gate | Status |
|---|---|
| MVP feature code (Phases 0–4, §2.1) | **Complete** |
| Portable onedir + local smoke | **Complete** (2026-08-09) |
| Product polish | **Complete** |
| Clean VM / two-PC / firewall / VC++ checklist | **Complete** |
| Latency numbers | **Complete** (within experimental targets) |
| 2 h / 8 h soak | **Complete** |

**Ship-ready for code + portable build:** yes.  
**Full §17 acceptance:** yes — all gates closed; see `ship-checklist.md`.
