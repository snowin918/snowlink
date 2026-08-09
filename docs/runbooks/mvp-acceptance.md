# MVP acceptance & soak runbook

Manual two-machine checklist for Snowlink MVP (PLAN §14 / §17).

## Preconditions

- Two Windows 11 PCs on the same physical LAN
- `pip install -e ".[dev,ui,capture,audio,webrtc]"` on both
- Optional: VPNs enabled with Allow LAN / split-tunnel (`docs/vpn-lan-access.md`)

## Functional checklist (§2.1)

1. Select physical adapter; confirm IPv4 shown
2. Share: monitor + loopback + preset → Start Sharing → note pairing code
3. View: IP + port + code → Connect → Approve on sharer
4. Confirm remote screen + system audio; Mute works
5. Stats panel shows FPS / bitrate / RTT / drops / A/V skew
6. Stop Sharing / Disconnect cleans up (port free; indicator cleared)
7. Second viewer while first connected → rejected (`VIEWER_SLOT_TAKEN`)
8. Diagnostics → Connectivity checklist (steps 1–7)

## Soak

| Duration | Focus | Pass criteria |
|---|---|---|
| 30 min | Stability smoke | No crash; FPS within ±10% of preset under light load |
| 2 h | Drift | `av_skew_ms` stays under ~100 ms or resync drops occur |
| 8 h | Memory | Growth &lt; 50–100 MB after warmup; no unbounded climb |

Record process CPU/memory via the Share/View stats panel (**CPU** / **RSS**) and/or:

```powershell
python scripts/dev/soak_sample.py --pid <SnowlinkPID> --duration-s 1800 --interval-s 30 --out soak-30m.jsonl
```

See [`mvp-ship-evidence.md`](mvp-ship-evidence.md) for dated results.

## Interrupt recovery

1. During Viewing, disable Wi-Fi or unplug Ethernet ~10 s, then restore
2. Expect `reconnecting` then resume within ~5 s, **or** clean fail with retry

## Latency (experimental ranges)

- Glass-to-glass video (Balanced/Low, wired): aim 80–200 ms
- Audio: aim 40–120 ms

Record method (phone timer / click sync) and values in a short note when validating a release.

## Packaging smoke

1. Build onedir: `python scripts/dev/build_gui_exe.py`
2. Copy `packaging/dist/Snowlink/` to a clean Win11 VM (no venv)
3. Launch `Snowlink.exe`; run Share/View + Diagnostics checklist
4. Confirm VC++ hint dialog if PyAV missing; firewall prompt on first listen
