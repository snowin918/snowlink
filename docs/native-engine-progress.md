# Snowlink Native Engine Progress

## Architecture

Python/PySide6 remains the control plane. Uncompressed frames do not cross the
C ABI. The native video path is now:

```
CaptureManager (auto | wgc | dxgi)
  -> WGC: GraphicsCaptureItem -> free-threaded frame pool
  -> DXGI: IDXGIOutput1::DuplicateOutput -> IDXGIOutputDuplication
  -> ID3D11Texture2D
  -> GPU CopyResource into a 2-slot Snowlink-owned latest-frame pool
  -> GpuFrameProcessor (D3D11 video processor: crop/rotate/scale/convert)
  -> pooled NV12 ID3D11Texture2D
  -> Media Foundation H.264 encoder MFT (D3D11 device manager)
  -> native EncodedFrame access units
  -> bounded native latest-frame queue
  -> H.264 RTP/FU-A packetizer
  -> ICE + DTLS-SRTP WebRTC transport
  -> network
```

There is no staging texture, `Map`, CPU readback, Python bytes, NumPy, OpenCV,
Qt image, or CPU BGRA step. The legacy Python DXcam/aiortc path is unchanged.

## Existing transport audit and compatibility

The working Python implementation is WebRTC through aiortc, not the Phase 0 TCP
diagnostic socket. Signaling is a sharer-hosted WebSocket on TCP port 3847. Its
versioned JSON envelopes perform hello, a nonce-bound 6-digit pairing challenge,
rate limiting, explicit sharer approval, and SDP offer/answer exchange. ICE is
non-trickle, host-candidate-only, bound to the selected LAN/VPN IPv4; there is no
STUN or TURN service. This intentionally assumes direct LAN or VPN reachability.

Media normally uses ICE-selected UDP, standard RTP/RTCP, DTLS certificate
fingerprints, and SRTP. UDP ports are ephemeral. RTP supplies a 16-bit sequence,
32-bit codec timestamp, SSRC, payload type, and marker bit. RTCP supplies sender
reports, receiver feedback, RTT, NACK, and PLI. WebRTC consent freshness is the
keepalive/liveness mechanism. DTLS-SRTP supplies encryption, integrity, and peer
fingerprint verification. Video retransmission is selective NACK rather than a
reliable byte stream; input/control reliability remains a separate concern.

The native sender preserves that protocol with pinned libdatachannel 0.24.3.
Existing aiortc viewers can answer its standards-based H.264 offer when H.264 is
enabled (`allow_h264_fallback` in the current viewer configuration). VP8 remains
the legacy Python sender default; native hardware output requires H.264. No raw
custom UDP media protocol was added.

## Native WebRTC sender

`Transport` creates a send-only H.264 WebRTC track. Python calls `connect`, asks
for an offer, transports SDP through the existing authenticated/approved
WebSocket exchange, applies the answer, then calls `start_stream`. The C ABI is:

```
snowlink_engine_connect_transport
snowlink_engine_create_transport_offer
snowlink_engine_get_local_sdp / _type
snowlink_engine_set_remote_sdp
snowlink_engine_start_stream / _stop_stream
```

The ctypes wrapper presents these as `NativeEngine.connect`, `create_offer`,
`local_description`, `set_remote_description`, `start_stream`, and
`stop_stream`. SDP polling is control traffic only. Python never receives an
`EncodedFrame`, NAL unit, RTP packet, or per-frame callback.

The stream worker observes the latest capture texture, submits GPU preprocessing,
wraps the resulting NV12 texture in a Media Foundation sample, drains compressed
H.264 access units, and moves them into `Transport`. A dedicated sender worker
packetizes and sends them. libdatachannel owns its ICE, DTLS, SRTP, and network
threads. Shutdown first stops/joins the stream worker, flushes encoder/processor
state, stops/joins the sender, closes the peer connection, and releases capture.
The same object can initialize a fresh peer connection for reconnect.

The encoder-to-transport queue defaults to two complete encoded frames and is
configurable but may not be zero. When full, the oldest frame is discarded so
new desktop state wins; no unbounded retry queue exists. The RTP NACK cache is
independently bounded to 256 packets. RTCP PLI/FIR invokes the hardware encoder's
native keyframe request directly. Congestion is visible upstream through queue
depth, dropped frames, send bitrate, RTT, and transport errors; dynamic bitrate
adaptation is deliberately left to session policy rather than hidden inside the
network thread.

`EngineStats` and the C/Python ABI expose `send_bitrate`, `packets_sent`,
`packets_dropped`, `transport_frames_dropped`, `transport_queue_depth`, `rtt`,
`estimated_loss`, and `transport_errors`. `estimated_loss` is reserved as zero
until receiver-report loss is surfaced by the selected WebRTC backend; it is not
fabricated from local queue drops.

### Packet format and MTU

The wire format is RFC 3550 RTP carrying RFC 6184 H.264 packetization-mode 1:

- the DTLS-SRTP association identifies the authenticated media session;
- SSRC identifies the video stream;
- the RTP timestamp identifies all packets belonging to one encoded frame and
  uses the standard 90 kHz video clock;
- the RTP 16-bit sequence orders packets and exposes gaps;
- the marker bit identifies the final packet of an access unit;
- H.264 IDR NAL type identifies keyframes;
- large NAL units use FU-A start/end fragments, while small NAL units remain
  single-NAL packets.

The configured path MTU defaults to 1200 bytes. The packetizer reserves transport
overhead and emits media fragments below that limit, avoiding intentional IP
fragmentation on normal IPv4, IPv6, LAN, and VPN paths. Encoded frames are never
assumed to fit one datagram. RTP sequence wrap and timestamp wrap use their
standard modular semantics.

### Security boundary

Pairing, rate limiting, one-viewer approval, and SDP carriage remain in the
existing Python WebSocket signaling layer. The approved SDP contains the DTLS
fingerprint; native libdatachannel performs ICE connectivity checks, DTLS, peer
fingerprint verification, SRTP key derivation, encryption, and authentication.
OpenSSL and libsrtp implement cryptography; Snowlink implements no cipher or key
exchange. The existing signaling channel is still plain `ws://` on the selected
LAN/VPN interface, so pairing approval is the signaling trust boundary exactly
as before; this phase does not claim TLS for signaling or cryptographically bind
the separate generated `session_secret` to DTLS.

## Shared capture abstraction and auto selection

`ICaptureBackend` is the common native producer contract. WGC and DXGI publish
an AddRef'd `ID3D11Texture2D`, monotonically increasing frame ID,
`FrameMetadata`, `PointerState`, status, and counters. `CaptureManager` owns one
backend and remains the single downstream entry point, avoiding backend-specific
encoder or network paths.

`CaptureBackend::Auto` (`-1`) tries WGC first and falls back to DXGI if WGC
cannot initialize. Explicit `Wgc` (`1`) and `Dxgi` (`0`) do not silently switch.
Runtime failover after a successful start remains orchestration work.

## WGC implementation

WGC continues to use programmatic monitor capture,
`Direct3D11CaptureFramePool::CreateFreeThreaded`, and two Snowlink-owned GPU
textures. Frame-pool surfaces are accessed as `ID3D11Texture2D` and copied with
`CopyResource`. Resize recreates the slots and WGC pool. Ordered shutdown
unregisters callbacks, closes session/pool, waits for callbacks, and releases
resources. Borderless capability checks and the independent WGC cursor toggle
remain unchanged; WGC is still the primary backend.

## DXGI Desktop Duplication

`DxgiCaptureBackend` enumerates monitors with `EnumDisplayMonitors`, matches the
selected `HMONITOR` to its adapter and `IDXGIOutput1`, creates D3D11 on that
adapter, and calls `DuplicateOutput`. A worker uses `AcquireNextFrame` with a
100 ms timeout. A scoped frame lease calls `ReleaseFrame` on every acquired
frame exit path, including errors.

The duplication description supplies desktop width, height, and
`DXGI_MODE_ROTATION`. Source-size changes rebuild only Snowlink's two GPU slots.
`DXGI_ERROR_ACCESS_LOST`, invalid duplication state, and temporarily unavailable
duplication cause teardown and periodic monitor/output/device re-enumeration.
This handles display-mode changes and disconnect/reconnect after topology
settles. Device removal is reported separately. Clean stop signals and joins the
worker; the bounded acquire timeout limits shutdown latency.

## Resource ownership

Each backend owns its D3D11 device/context and two default-usage publication
textures. WGC pool surfaces and DXGI acquired surfaces are temporary producer
resources. Before releasing them, Snowlink performs a GPU `CopyResource` into a
publication slot. `get_latest_frame` returns an AddRef'd slot texture; the caller
releases it. No CPU pixel copy is performed.

`GpuFrameProcessor` obtains the capture texture's D3D11 device and uses that
device's immediate video context. Its output is therefore directly consumable
by a hardware encoder on the same device. Cross-device use will require explicit
shared-resource synchronization and is not part of this phase. D3D11 multithread
protection is enabled because capture and processing may submit from different
threads through the device's shared immediate context.

## Common GPU preprocessing

The common processor uses the D3D11 video processing API
(`ID3D11VideoProcessor`) rather than a CPU conversion path or custom shaders.
`VideoProcessorBlt` performs source cropping, optional scaling, rotation (through
`ID3D11VideoContext1`), and color conversion in one GPU submission. Driver format
support is checked when resources are created, so unsupported input/output
combinations fail explicitly.

The primary output is `DXGI_FORMAT_NV12`. The small public format abstraction also
defines P010 and BGRA for future encoder/HDR paths; availability remains dependent
on the display driver's video processor. NV12 and P010 output dimensions must be
even. Target dimensions may be independent of capture dimensions (for example,
2560x1440 or 3840x2160 to 1920x1080); zero target dimensions select the natural
post-crop, post-rotation size.

Two default-usage output textures and their video output views are allocated as a
reusable pool. Input views are cached for the two capture publication textures.
The pool is recreated only when the D3D device, source size/format, crop size,
target size, or output format changes. No staging resource, `Map`, upload, `Flush`,
GPU query, `GetData`, or CPU wait exists in the normal preprocessing path.

`process_frame` records GPU work and publishes one output slot; `get_latest_frame`
returns an AddRef'd texture that the caller releases. Publication is latest-only:
an unobserved output is replaced and counted rather than appended to a queue.
Together with capture's existing latest-frame pool, this bounds both sides of the
processor. The future encoder must submit its read on the same ordered D3D11
device/context before a pooled slot is reused, or add explicit synchronization
if it uses a separate context/device.

Statistics include `gpu_preprocess_frames`, unobserved `frames_replaced`, pool
`resolution_changes`, and average CPU submission latency. GPU timing queries are
intentionally omitted because collecting exact completion time would add waits.

Known limitations: format conversion, scaling quality, and maximum dimensions are
driver-dependent; rotation needs `ID3D11VideoContext1`; color-space/range controls
currently use the driver's SDR defaults. Media Foundation samples retain
submitted textures, and the MFT is bound to the same D3D11 device. Cross-device
encoder input remains unsupported and is rejected explicitly.

## Native H.264 encoding

`IVideoEncoder` is the native contract. `H264HardwareEncoder` implements it with
Media Foundation encoder MFTs and supports width, height, FPS, bitrate, keyframe
interval, low-latency mode, CBR/VBR, and hardware policy. It exposes
`initialize`, `encode`, `request_keyframe`, `set_bitrate`, `set_fps`, and
`shutdown`.

Initialization uses `MFTEnumEx` to request a hardware H.264 encoder. The selected
activation's friendly name is reported with inferred vendor, codec, Main profile,
resolution, FPS, bitrate, and a hardware boolean. That boolean is true only for a
transform returned by hardware-only enumeration; codec availability is not
mistaken for hardware acceleration.

`RequireHardware` is the default and fails explicitly when no hardware MFT can
be activated. `PreferHardware` likewise does not silently change the performance
model. Software is tried only for explicit `AllowSoftwareFallback`, and is
reported as `hardware_accelerated=false`. There is no x264 path.

An `IMFDXGIDeviceManager` binds the hardware MFT to the processor's D3D11 device.
`MFCreateDXGISurfaceBuffer` wraps each NV12 `ID3D11Texture2D` directly. There is
no staging texture, `Map`, raw CPU copy, or Python object in the normal path;
only compressed H.264 output is copied into native `EncodedFrame` storage.

Low-latency codec attributes request one reference frame, short GOPs, and no
unnecessary reordering. Asynchronous hardware MFT events are pumped without
blocking; when the encoder cannot accept input, the latest frame is dropped
instead of queued without bound. `request_keyframe` uses `ICodecAPI`.
`set_bitrate` changes `CODECAPI_AVEncCommonMeanBitRate` dynamically and returns a
driver error if unsupported. `set_fps` changes timestamp cadence without an
application teardown; mid-stream media-type renegotiation is avoided because it
is driver-dependent.

## Dirty/move metadata and cursor

Each DXGI frame retains QPC timestamp, dimensions, desktop/pointer update flags,
`GetFrameDirtyRects`, and `GetFrameMoveRects` results. Metadata and shape vectors
are resized in place so their capacity is reused across frames. The data remains
available for later change detection, scheduling, bandwidth, and encoder
decisions. No custom tile codec has been added.

Pointer position, visibility, shape-change state, shape bytes, type, dimensions,
pitch, and hotspot come from duplication frame information and
`GetFramePointerShape`. Cursor state is stored independently and is not drawn
into the desktop texture. WGC still exposes its native cursor-compositing toggle.

## Build and test

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/build_native_engine.ps1
native\build\bin\Release\snowlink_capture_test.exe --backend wgc --monitor 0 --seconds 10
native\build\bin\Release\snowlink_capture_test.exe --backend dxgi --monitor 0 --seconds 30
native\build\bin\Release\snowlink_capture_test.exe --backend auto --monitor 1 --seconds 30
native\build\bin\Release\snowlink_capture_test.exe --backend auto --monitor 0 --seconds 30 --preprocess
native\build\bin\Release\snowlink_capture_test.exe --backend dxgi --monitor 0 --seconds 30 --target 1920 1080
native\build\bin\Release\snowlink_encoder_benchmark.exe --backend auto --monitor 0 --seconds 30 --target 1920 1080 --fps 60 --bitrate 8000000
native\build\bin\Release\snowlink_transport_packet_test.exe
.\.venv\Scripts\python.exe -m pytest tests/unit/test_native_engine_lifecycle.py tests/unit/test_native_engine_backend.py -q
```

The native build fetches pinned libdatachannel commit
`c6696d157b5612df2a741d9a03b192b47ab6cefb` and requires OpenSSL 1.1 or newer.
On Windows, CMake copies the discovered OpenSSL runtime DLLs beside
`snowlink_engine.dll`; production packaging must include those files and their
applicable licenses.

Transport validation on 2026-08-09:

- Release `snowlink_engine.dll` and the packet test compile with VS 2022,
  Windows SDK 10.0.26100, libdatachannel 0.24.3, libsrtp, and OpenSSL 3.0.21.
- An 8197-byte Annex-B IDR access unit produced nine RTP/FU-A packets; every
  packet was at most 1200 bytes and ordered reconstruction matched byte-for-byte.
- Reordered fragments reconstructed correctly. Removing a middle FU-A fragment
  prevented the damaged frame from comparing as complete.
- Python control-plane tests generated a host-only native offer, exercised clean
  shutdown, and passed 7/7. No per-frame Python API exists.
- A new `connect` call closes the prior peer and constructs fresh ICE/DTLS state.
- RTCP NACK support is bounded to 256 cached packets and RTCP PLI/FIR is wired to
  `H264HardwareEncoder::request_keyframe`.
- A live two-machine encrypted media run still requires two interactive Windows
  desktops because capture is unavailable in the automation desktop. Validate
  reconnect, real network loss, RTT/loss stats, and receiver-driven PLI there;
  this phase makes no claim that those environment-dependent checks ran here.

The test selects auto/WGC/DXGI, acquires only GPU textures, and prints periodic
and final FPS, dimensions, rotation, dirty/move counts, cursor updates, timeouts,
and recovery statistics. It never dumps or maps frames. DXGI access-loss recovery
can be tested by changing display mode or disconnecting/reconnecting the monitor.

Validation on 2026-08-09:

- Release DLL and capture test compile successfully with VS 2022 and Windows SDK
  10.0.26100.
- WGC cannot start in the automated execution desktop because the capture service
  is absent (`0x80070424`).
- DXGI `DuplicateOutput` returns `0x80070005` (`E_ACCESSDENIED`) in this
  non-interactive/secure automation desktop. Live FPS, metadata, cursor, and
access-loss recovery verification therefore require an interactive desktop.

The optional `--preprocess` path submits each newly observed capture texture to
the GPU processor, obtains the latest NV12 GPU texture, and discards it without
encoding. `--target W H` additionally tests scaling. This path never maps a
texture or reads screen pixels back to the CPU.

The encoder benchmark runs capture -> GPU process -> H.264 encode and discards
native compressed frames. It reports capture FPS, encode FPS, encoded Mbps,
keyframes, drops, exact encoder name, hardware true/false, and process CPU once
per second. Hardware is required by default. `--allow-software` is an explicit
diagnostic fallback and visibly reports `hardware=false` when used.

Encoder-phase validation on 2026-08-09:

- The Release DLL, capture test, and encoder benchmark compile with VS 2022 and
  Windows SDK 10.0.26100.
- This automated execution desktop cannot enter the live pipeline: WGC is
  unavailable and DXGI returns `0x80070005` (`E_ACCESSDENIED`). The benchmark
  exits with `capture start failed: -2147024891`, so no encoder identity or live
  throughput is claimed here.
- Run the benchmark on an interactive Windows desktop to record live hardware
  selection and throughput. A successful run prints the exact MFT name and
  `hardware=true` before periodic statistics.

## Remaining work

## Native receiver, hardware decode, and D3D11 presentation

The interactive View path now keeps video entirely native:

```
ICE + DTLS-SRTP WebRTC transport
  -> RtcpReceivingSession (RR/PLI)
  -> H.264 RTP depacketizer (complete Annex-B access units)
  -> 2-access-unit newest-frame queue
  -> hardware-only Media Foundation H.264 decoder MFT
  -> DXGI-backed NV12 ID3D11Texture2D
  -> D3D11 video-processor blit
  -> flip-model DXGI swap chain
  -> Qt-owned native child HWND
```

`IVideoDecoder` is the receiver-side codec contract. Its
`H264HardwareDecoder` implementation enumerates only hardware Media Foundation
H.264 decoder MFTs, enables low latency, binds an `IMFDXGIDeviceManager`, and
requires DXGI-backed NV12 output. It reports the exact decoder friendly name,
hardware status, decoded dimensions, decoded-frame count, corrupt-frame count,
and rolling decode FPS. Output surfaces remain on the receiver's D3D11 device;
there is no `Lock`, staging texture, NumPy array, `QImage`, or `QPixmap` in the
active View video path.

The decoder accepts Annex-B access units, including initial and changed SPS/PPS
configuration. `MF_E_TRANSFORM_STREAM_CHANGE` selects a new NV12 output type and
updates the published resolution. A decoder failure flushes the MFT, discards
inter frames until an IDR arrives, and sends RTCP PLI through libdatachannel.
libdatachannel's depacketizer does not publish incomplete FU-A frames. This keeps
loss recovery explicit rather than continuing indefinitely with a damaged
reference chain. Decoder/device recreation after hard device removal is still
remaining orchestration work.

`Renderer` owns the DXGI flip-discard swap chain and a native render worker. It
uses the D3D11 video processor to convert the decoded NV12 texture directly into
the BGRA swap-chain buffer. Source and destination rectangles preserve aspect
ratio with black letter/pillar boxing. Client size is checked on each new frame;
Qt resize/show/hide events also mark the swap chain for resize and suspend work
while hidden. The same native child surface is reparented into the existing
fullscreen window, so fullscreen does not create a Python pixel copy.

Qt remains responsible for the surrounding mute/fullscreen/disconnect controls,
status, and statistics. It creates a `WA_NativeWindow` child and passes only its
integer HWND through ctypes. Python carries paired signaling SDP and polls state
and decoder statistics; it receives no access units or video pixels. Network
callbacks only replace entries in a two-frame native queue. Decode and render
run on separate native workers, and presentation is latest-only: queued old
access units and an unpresented old texture are replaced. The renderer wakes for
a changed frame or a surface-state change and does not continuously repaint an
unchanged desktop frame.

Build validation on 2026-08-10:

- Release `snowlink_engine.dll` builds with VS 2022 and Windows SDK 10.0.26100.
- Native lifecycle/backend tests pass 7/7, and the Python package compile check
  passes.
- Live loopback and two-machine validation cannot run in the non-interactive
  automation desktop. On two interactive Windows machines, still verify first
  SPS/PPS/IDR startup, resize, fullscreen, DPI/monitor transitions, minimize and
  restore, reconnect, sender resolution change, induced RTP loss/PLI recovery,
  and the reported hardware decoder name/status.

### Receiver remaining work

- Add an automated encoded H.264 fixture/loopback receiver executable with
  deterministic packet removal, SPS/PPS changes, and PLI assertions.
- Recreate decoder, swap chain, and D3D11 device after hard device removal and
  adapter migration; current resize/minimize/monitor handling assumes the device
  remains valid.
- Integrate native audio receive or explicitly coordinate a separate audio-only
  peer; the new native View negotiation currently implements video only.
- Surface connection/error/statistics changes as a native event queue instead of
  polling them at control-plane cadence.

- Run and record WGC and DXGI benchmarks on an interactive physical/VM desktop,
  including display-mode change and monitor disconnect/reconnect.
- Complete production MSIX identity/signing/assets for optional WGC borderless
  capture.
- Add production runtime failover/backoff above `CaptureManager`.
- Run and record encoder benchmarks on representative Intel, NVIDIA, and AMD
  systems where available.

## Next phase

Next phase: implement native cursor and remote-input path.
