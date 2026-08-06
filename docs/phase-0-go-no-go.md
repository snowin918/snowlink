# Phase 0 go / no-go review

**Product:** Snowlink  
**Scope:** Phase 1 screen-only demo readiness (vpn-on-on network gate only)  
**Review host date (UTC):** 2026-08-06  
**Decision:** `GO` (with constraints)

---

## 1. Executive decision

**`GO`** — Phase 1 screen-only Share/View may proceed / ship as a LAN demo.

Network evidence gate is **vpn-on-on only** (asymmetric / VPN-off scenarios are
not required). Balanced capture does **not** meet 30 FPS on the lab host; Phase 1
defaults to the **Low** preset (`854×480@15`).

---

## 2. Experiment summary (updated)

| Experiment | Status | Notes |
| ---------- | ------ | ----- |
| A | PASS | Local adapter enum/bind + automated tests |
| B | PASS | `vpn-on-on` client echo on physical LAN IPv4 `192.168.139.20` (same host under Astrill VPN; true two-PC still recommended for ops) |
| C | WARN → constrained GO | 60 s Balanced DXGI ≈ **21.3 FPS** (below 27). Phase 1 default = **Low** |
| D | WARN | Not required for Phase 1 |
| E | PASS (local) | Synthetic VP8 loopback ICE `completed`; frames received. Archive under `experiment-results/experiment-e/` |
| F | WARN | Not required for Phase 1 |

Automated: pytest / ruff / mypy expected green after Phase 1 changes.

---

## 3. Phase 1 constraints (authorized)

- Default quality preset: **Low** (`854×480@15`); Balanced/High remain selectable but may miss FPS targets on software VP8.
- Capture backend: **DXGI** default.
- Signaling: experiment HTTP offer/answer bound to selected IPv4 (no pairing yet).
- ICE: host-only, no STUN/TURN.
- No system audio / pairing in this demo.
- Operator should still confirm **two distinct PCs** with both VPNs on before treating vpn-on-on as production-proven.

---

## 4. Selected Phase 1 technical choices

| Choice | Decision |
|---|---|
| screen-capture backend | DXGI |
| default preset | Low (Balanced deferred until FPS gate met) |
| codec | VP8 |
| signaling port | 3847/tcp |
| ICE policy | Host-only |
| queues | Latest-frame depth 1 |

---

## 5. Recommendation

* **Final decision:** `GO` (constrained)
* **Reason:** B vpn-on-on LAN bind/echo archived; C 60 s run archived with FPS constraint; E local synthetic VP8 passes; Phase 1 screen path implemented.
* **Exact next task after demo:** Phase 2 system audio; Phase 3 WebSocket pairing.
