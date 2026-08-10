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
```

There is no staging texture, `Map`, CPU readback, Python bytes, NumPy, OpenCV,
Qt image, or CPU BGRA step. The legacy Python DXcam/aiortc path is unchanged.

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
```

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

- Run and record WGC and DXGI benchmarks on an interactive physical/VM desktop,
  including display-mode change and monitor disconnect/reconnect.
- Complete production MSIX identity/signing/assets for optional WGC borderless
  capture.
- Add production runtime failover/backoff above `CaptureManager`.
- Run and record encoder benchmarks on representative Intel, NVIDIA, and AMD
  systems where available.

## Next phase

Next phase: build native low-latency media transport.
