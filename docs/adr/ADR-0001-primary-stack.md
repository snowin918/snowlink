# ADR-0001 — Primary stack

- **Status:** Accepted
- **Date:** 2026-08-06
- **Deciders:** Snowlink MVP engineering plan (`PLAN.md`)

## Context

Snowlink is a private, peer-to-peer Windows 11 desktop application that lets
exactly two computers on the same physical LAN share screen video and Windows
system audio in real time. The MVP must:

- Bind signaling to a selected physical LAN IPv4 (VPN adapters excluded by default)
- Transport media with low latency over the LAN without cloud relays or TURN
- Capture the desktop and WASAPI system-audio loopback (not the microphone)
- Present a native desktop UI with Share and View modes
- Remain a fast private MVP in Python before any native helper investment

Raw UDP media, commercial remote-control features, and internet relays are out
of scope. Phase 0 experiments must validate capture, audio, and WebRTC path
selection before deep UI investment.

## Decision

Proceed with a **Python 3.12+** MVP using WebRTC for media, a sharer-hosted
WebSocket signaling server, DXGI Desktop Duplication for screen capture, WASAPI
loopback for system audio, and PySide6 for the desktop UI. Media transport is
**not** raw UDP.

## Selected technologies

| Layer | Choice | Notes |
|---|---|---|
| Runtime | Python 3.12 or newer | Pinned via `requires-python` in `pyproject.toml` |
| Media transport | aiortc | WebRTC; VP8 video + Opus audio; DTLS-SRTP |
| Concurrency | asyncio | Owns signaling and WebRTC on a dedicated thread |
| Screen capture | DXcam (DXGI backend default) | Desktop Duplication API |
| System audio | PyAudioWPatch | WASAPI loopback; no microphone in MVP |
| Frame conversion | PyAV | `VideoFrame` / `AudioFrame` bridging |
| Desktop UI | PySide6 | Viewer and share controls; capture/network off UI thread |
| Signaling | aiohttp WebSocket server on sharer | Viewer dials `ws://<selected-ip>:<port>` |
| Validation | pydantic v2 | Versioned signaling schemas (when messaging lands) |
| Tests | pytest + pytest-asyncio | Unit, protocol, and integration |
| Packaging | PyInstaller | Portable onedir first |

Quality presets for the MVP: Low `854×480@15`, Balanced `1280×720@30` (default),
High `1920×1080@30`. Video uses a latest-frame / depth-1 queue; audio uses a
small bounded ring buffer with audio-primary A/V sync.

## Alternatives considered

| Alternative | Why not selected for MVP |
|---|---|
| C# / WPF + native WebRTC | Strong Windows fit, but slower private MVP iteration and heavier packaging story for this team |
| Electron + browser `getDisplayMedia` | Weaker control over bind address, VPN path selection, and system-audio loopback semantics |
| Go + Pion | Excellent WebRTC stack, but splits the app across languages for UI/capture orchestration |
| Raw UDP custom media | Explicitly rejected; loses DTLS-SRTP, congestion control, and codec negotiation |

## Consequences

**Positive**

- Matches the required Python stack and enables rapid Phase 0 validation scripts
- aiortc provides a standard WebRTC path (VP8/Opus) without deploying TURN
- Sharer-hosted WebSocket signaling keeps the offline two-PC UX simple
- Constructor-injected narrow protocols can keep capture and networking testable

**Negative / trade-offs**

- Software VP8 encode at High preset is expected to be CPU-heavy
- Extra RGB↔YUV copies via PyAV add measurable latency
- Packaging must ship native wheels (aiortc, PyAV, DXcam, PyAudioWPatch, PySide6)
- Qt and asyncio must be bridged carefully (dedicated asyncio thread preferred)

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Software VP8 CPU too high at High / Balanced | Poor glass-to-glass latency or fan load | Default Balanced; measure in Phase 0/1; cap High as experimental if needed |
| Packaging native dependencies fails on target PCs | Install/distribution friction | Prefer wheels; PyInstaller onedir; document Visual C++ runtime if required |
| VPN / wrong interface breaks LAN media path | Sessions fail despite “same LAN” | Adapter classification, bind-to-selected-IP, host-candidate preference (later ADRs) |
| Capture or loopback APIs unstable under fullscreen / DRM | Blank or silent streams | Phase 0 experiments C–F; documented fallbacks |

## Fallback strategy

1. Keep Python for orchestration, signaling, UI, and session control.
2. If Phase 0 shows latency or CPU outside workable ranges at Balanced, schedule a
   **native helper** for capture and/or hardware encode earlier, while retaining
   the same application architecture.
3. Capture fallback path: DXcam `winrt` backend, then a native Windows.Graphics.Capture helper.
4. Encode fallback path: lower preset first; hardware encode (NVENC/QSV/AMF) via helper later.
5. UI/async bridge fallback: `qasync` if the dedicated asyncio-thread approach proves awkward.

Runtime libraries listed above are **not** installed in this repository skeleton;
they land when Phase 0 experiments and application modules need them.
