# Snowlink Native Engine Architecture

## 1. Overall architecture

Python/PySide6 is the control plane for UI, authenticated signaling, approval,
configuration, and once-per-second diagnostics. The active `native_cpp` media
plane is C++: GPU capture, processing, H.264, WebRTC transport, decoding, D3D11
presentation, cursor, and input. Raw video frames never cross the C ABI.

## 2. Thread diagram

```text
WGC callback or DXGI capture worker
  -> two-slot latest capture texture pool
native stream worker
  -> eight-surface bounded processed texture ring
encoder input worker
  -> two-texture newest-frame queue -> Media Foundation input
Media Foundation event/output worker
  -> bounded compressed output queue (4)
native transport sender
  -> bounded encoded-frame queue (2 by default) -> libdatachannel workers
libdatachannel receive callback
  -> bounded access-unit queue (2)
native decode worker
  -> latest decoded texture
native render worker
  -> flip-model swap chain

cursor sampler (sender) -> SCTP cursor channels -> cursor overlay (receiver)
Qt/native input events -> SCTP input channel -> SendInput worker boundary
```

Shutdown signals workers, joins stream/decode/render/capture-owned threads, then
releases codecs, transport, capture resources, and devices. No video queue is
unbounded.

## 3. GPU pipeline

WGC or DXGI supplies a BGRA `ID3D11Texture2D`. `CopyResource` publishes it into
two default-usage textures. A D3D11 video processor crops, rotates, scales, and
converts to pooled NV12 textures. Media Foundation consumes the DXGI surface on
the same device. The receiver decodes to DXGI-backed NV12 and video-processor
blits directly to a BGRA swap-chain buffer. There are no staging resources,
`Map`, `GetData`, full-frame CPU copies, or Qt/OpenCV conversions in this path.

## 4. Capture backends

`CaptureManager` exposes one interface. Automatic selection tries WGC then DXGI;
explicit selection does not silently switch. WGC uses a free-threaded frame
pool. DXGI uses Desktop Duplication with a bounded 100 ms acquire timeout and
recreates duplication after access loss. DXGI duplication/copy work runs on a
capture-only D3D11 device. Two keyed-mutex shared textures cross to a separate
video device, where they are copied into a two-slot latest-frame pool before GPU
processing. This prevents duplication-driver context serialization from stalling
the processor or encoder without a CPU transfer. Pointer-only DXGI frames update
cursor metadata but are not published to the video pipeline.

WGC borderless capture is conditional on OS capability, application identity,
and user permission. Diagnostics distinguish granted borderless capture from an
active Windows capture border. Production MSIX identity/signing remains open.

## 5. Encoder and decoder

The sender uses a Media Foundation H.264 MFT with an
`IMFDXGIDeviceManager`. Hardware is required by default; software is used only
under the explicit fallback policy and is reported as such. The receiver
enumerates hardware-only Media Foundation H.264 decoders and requires DXGI NV12
output. Decoder corruption/reset discards inter frames until IDR and requests a
new keyframe with RTCP PLI.

## 6. Network transport

libdatachannel 0.24.3 provides ICE, DTLS-SRTP, RTP/RTCP, and SCTP. Signaling is
the existing approved WebSocket exchange. H.264 uses RFC 6184 packetization-mode
1 with FU-A fragmentation and a 1200-byte default MTU. The encoded-frame queue
defaults to capacity 2 and drops oldest. The RTP NACK cache is bounded to 256
packets.

## 7. Cursor channel

Cursor motion is unordered with zero retransmissions; shapes are ordered and
reliable and sent only when their content identity changes. The receiver caches
shapes and displays a transparent overlay. Cursor updates do not trigger video
encoding. Cursor bitmap allocation/copy occurs on shape or display updates, not
for every screen-video frame.

## 8. Input path

Mouse, wheel, and keyboard messages use an ordered reliable SCTP channel.
Coordinates are inverse-mapped through letterboxing and then into the selected
virtual-desktop monitor rectangle. Injection is authorized only after pairing,
approval, connection, and active streaming, and is revoked on stop.

## 9. Python/native boundary

ctypes carries configuration, SDP, HWND values, input events, status, and
aggregate statistics. It carries no video pixel buffers, encoded access units,
RTP packets, or per-frame callback. QImage/QPixmap/OpenCV screen conversion is
retained only by the explicitly selected `legacy_python` backend.

## 10. Failure recovery

DXGI recreates duplication after access loss and reports device removal. WGC
recreates its pool on size change. Encoder backpressure drops the newest submit
rather than accumulating work. Decoder errors flush, wait for IDR, and request
PLI. Reconnect creates new ICE/DTLS state. Hard GPU device removal and adapter
migration still require complete decoder/renderer recreation orchestration.

## 11. Build instructions

Use `scripts/dev/build_native_engine.ps1` with `-Config Release` or `-Config
Debug`. Requirements are VS 2022 C++, Windows SDK, CMake, and OpenSSL 1.1 or
newer. CMake fetches pinned libdatachannel commit
`c6696d157b5612df2a741d9a03b192b47ab6cefb`. Package the discovered OpenSSL
runtime DLLs and applicable licenses with `snowlink_engine.dll`; Windows Media
Foundation and D3D11 are OS runtime dependencies.

## 12. Runtime diagnostics

Capture status exposes active backend, border/borderless state, resolution,
rotation, access loss, and device loss. Encoder and decoder selection must be
reported by exact MFT name with hardware status. Statistics expose capture,
encode, decode, and render counts/FPS where implemented, bitrate, RTT, transport
queue depth, packet/frame drops, and transport errors. Exact GPU/VRAM and stage
latencies are benchmark-only until low-overhead measurements are validated.

## 13. Known limitations

Interactive two-machine benchmarks and failure-matrix runs are outstanding.
Runtime WGC-to-DXGI failover is not orchestrated after a successful start. Hard
receiver GPU reset/adapter migration is incomplete. Native audio integration,
production MSIX identity/signing, receiver event delivery, and representative
Intel/NVIDIA/AMD qualification remain open. WGC cannot provide DXGI dirty rects,
so it relies on frame arrival semantics rather than explicit dirty metadata.

## Queue audit

| Boundary | Capacity | Full/replace policy | Producer | Consumer |
|---|---:|---|---|---|
| capture -> process | 2 textures, latest-only | replace unobserved slot | WGC callback or DXGI worker | stream worker |
| process -> encoder input | 2 texture references over an 8-surface GPU ring | consume newest and clear stale | stream worker/GPU processor | encoder input worker/MFT |
| encoder output -> stream | 4 access units | drop oldest | MFT event/output worker | stream worker polling |
| stream -> network | 2 access units by default | drop oldest | stream worker | transport sender worker |
| network -> decode | 2 access units | drop oldest; decoder consumes newest and clears stale | libdatachannel callback | decode worker |
| decode -> renderer | 1 latest texture | replace unpresented texture | decode worker | render worker |
