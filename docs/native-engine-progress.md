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
  -> future native processor/encoder
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

The future processor/encoder should consume textures on the backend device or
use explicit D3D shared-resource synchronization.

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

## Remaining work

- Run and record WGC and DXGI benchmarks on an interactive physical/VM desktop,
  including display-mode change and monitor disconnect/reconnect.
- Complete production MSIX identity/signing/assets for optional WGC borderless
  capture.
- Add production runtime failover/backoff above `CaptureManager`.
- Feed the common GPU texture/metadata contract into preprocessing and encoding.

## Next phase

Next phase: build shared D3D11 GPU preprocessing and zero-copy frame pipeline.
