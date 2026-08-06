# Phase 0 experiments

This directory holds **disposable technical-validation scripts** for Phase 0.
Scripts prove risky dependencies work in isolation on Windows 11 (including with
VPNs connected) before the full application is built.

**Status:** Harness only — experiments A–F are **not implemented yet**.

Do not treat scripts here as production modules. Prefer printed pass/fail output
and optional metrics JSON. Document VPN failure modes for Experiment B into
`docs/vpn-lan-access.md` when that experiment is complete.

## Experiment overview

| ID | Purpose | Demonstrates |
|---|---|---|
| **A** | Adapter enumeration, classification, and bind-to-selected-IP TCP echo | Physical LAN IPv4 selection; VPN/virtual adapters excluded by default; listener bound to the chosen address |
| **B** | Two-machine TCP connect with **both VPNs enabled** | Real LAN reachability under VPN; failure modes for allow-LAN / split-tunnel guidance |
| **C** | DXcam capture → local PySide6 or OpenCV preview + FPS/latency counters | Desktop Duplication viability and capture cost before WebRTC |
| **D** | WASAPI loopback → local playback + underrun metrics | System-audio capture (not microphone) and buffer health |
| **E** | aiortc connection using a **synthetic video** track (same-machine two-process preferred) | WebRTC video path and host-candidate / ICE behavior without real capture |
| **F** | aiortc connection using a **synthetic audio** track + Opus playback | WebRTC audio path and Opus decode/playback without loopback hardware issues |

## Execution order

1. **Experiment A** first — foundation for VPN-safe networking.
2. **Experiment B** next — two-machine reachability before heavy media work.
3. Then **C** and **E** (video capture + synthetic WebRTC video), and **D** and **F**
   (loopback + synthetic WebRTC audio), as needed for the Phase 0 go/no-go gate.

## Go / no-go gate (from PLAN.md)

If Experiments **C**, **E**, and **F** meet rough latency/CPU bars for the
Balanced preset (`1280×720@30`), begin Phase 1 (screen-only prototype).
Otherwise keep the architecture but schedule a native capture/encode helper
spike before investing in full Phase 3 UI work.

## What belongs here later

When implemented, expect one script (or small pair of scripts) per experiment,
plus short result notes. Do **not** add application UI, signaling product code,
or packaging from this folder.
