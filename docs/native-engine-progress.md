# Snowlink Native Engine Progress

## Architecture

Python/PySide6 remains the control plane. Uncompressed frames do not cross the
C ABI. The native video path is now:

```
GraphicsCaptureItem (monitor)
  -> Direct3D11CaptureFramePool::CreateFreeThreaded (2 WGC buffers)
  -> IDirect3D11Texture2D via IDirect3DDxgiInterfaceAccess
  -> GPU CopyResource into a 2-slot Snowlink-owned latest-frame pool
  -> future native encoder
```

There is no staging texture, `Map`, CPU readback, Python bytes, NumPy, OpenCV,
Qt image, or CPU BGRA step in this path. The legacy Python DXcam/aiortc path is
unchanged and remains the shipping stream path until the later encoder and
transport phases are complete.

## WGC implementation

- `native/include/snowlink/capture/wgc_capture_backend.h`: GPU texture producer
  API and status/stats access.
- `native/src/capture/wgc_capture_backend.cpp`: WGC monitor interop, D3D11
  device, free-threaded frame pool, GPU frame copy, resize, access/device-loss
  detection, border/cursor controls, and ordered shutdown.
- `native/src/capture/capture_manager.cpp`: backend selection and ownership.
  Native backend `1` is WGC; `0` is reserved for Desktop Duplication.
- `native/tools/capture_test.cpp`: GPU-only development benchmark.
- `packaging/msix/AppxManifest.xml`: package manifest template containing the
  supported restricted `graphicsCaptureWithoutBorder` capability.
- `native/include/snowlink/c_api.h`, `native/src/c_api.cpp`, and
  `src/snowlink/native_engine/engine.py`: control/status exposure to Python.

## Device and frame ownership

Each `WgcCaptureBackend` owns one hardware D3D11 device and immediate context,
created with `D3D11_CREATE_DEVICE_BGRA_SUPPORT`. That device is wrapped with
`CreateDirect3D11DeviceFromDXGIDevice` for WGC. The future processor/encoder
must consume textures from this same device or explicitly use D3D shared-resource
synchronization.

WGC owns/recycles its frame-pool surfaces. The frame callback obtains their
underlying `ID3D11Texture2D` using `IDirect3DDxgiInterfaceAccess`, then executes
`ID3D11DeviceContext::CopyResource` into one of two Snowlink-owned default-usage
textures. Publishing replaces the stale slot. `get_latest_frame` returns an
AddRef'd COM pointer; the caller releases it. This gives the consumer stable GPU
resource ownership without keeping a recyclable WGC frame alive and without CPU
readback. Replacements are counted when a producer overwrites a frame not yet
acquired by the consumer.

## Threading and shutdown

The backend uses `Direct3D11CaptureFramePool::CreateFreeThreaded`; `FrameArrived`
runs on the pool's internal worker thread and never on the PyQt thread. A mutex
protects the two-slot publication state; atomics hold cheap counters/status.

Shutdown marks the backend stopping, unregisters `FrameArrived` and item-closed
handlers, closes the session and frame pool, waits (bounded to two seconds) for
in-flight callbacks, releases queued textures, then releases the WinRT and D3D
objects. Weak callback ownership prevents callbacks from resurrecting or using a
destroyed backend.

## Resize, display changes, and loss behavior

The callback compares `Direct3D11CaptureFrame::ContentSize` with the published
size. A change reallocates both native GPU textures and calls frame-pool
`Recreate`; this handles resolution/orientation/display-mode changes without CPU
frames. `GraphicsCaptureItem::Closed` marks access lost and capture inactive.
D3D11 `GetDeviceRemovedReason` marks device loss and capture inactive. These are
exposed to the control plane; stop followed by start recreates the capture target,
device, pool, and session cleanly. Automatic retry policy is intentionally left
to session orchestration so unplugged displays do not create an infinite native
retry loop.

## Borderless capture

Snowlink uses only the documented flow:

1. Confirm the process has package identity and the access API is present.
2. Call `GraphicsCaptureAccess::RequestAccessAsync(Borderless)`.
3. If Windows returns `Allowed`, call `GraphicsCaptureSession::IsBorderRequired(false)`.
4. Otherwise continue capture with the system border.

`borderless_capture_available`, `borderless_capture_granted`, and
`capture_border_active` are exposed through the C ABI and Python wrapper.
Unpackaged development builds report borderless unavailable and do not call the
restricted API. Release packaging must provide package identity and declare:

```xml
<rescap:Capability Name="graphicsCaptureWithoutBorder" />
```

The template at `packaging/msix/AppxManifest.xml` does this. Its publisher,
version, and asset placeholders must be replaced/signing configured in the
packaging phase. Permission denial is non-fatal; Snowlink keeps the supported
Windows capture border. No overlay, cropping, DWM manipulation, patching, or
security-UI suppression is used.

## Programmatic monitor capture and cursor

Snowlink preserves zero-based monitor selection by enumerating monitors with
`EnumDisplayMonitors`, then uses the documented
`IGraphicsCaptureItemInterop::CreateForMonitor`. This desktop interop is available
from Windows 10 version 1903 (build 18362) and does not require the picker.
Package identity is needed for the restricted borderless capability, not for
ordinary programmatic monitor interop.

`capture_cursor_in_video` is exposed before and during capture and maps to
`GraphicsCaptureSession::IsCursorCaptureEnabled`. It defaults to `false` on the
native path in preparation for separate cursor metadata. On systems where that
session interface is unavailable, the setter failure is handled without touching
pixels; the status remains truthful about the requested/applied native setting.

## OS and fallback requirements

- Programmatic monitor WGC: Windows 10 1903 / build 18362 or newer.
- Free-threaded frame pool: Windows 10 1809 or newer (therefore covered above).
- Cursor toggle: Windows 10 2004 / build 19041 or newer.
- Borderless access/session control: Windows Server 2022 build 20348 or Windows
  11, plus package identity, manifest capability, and user/administrator policy.
- If WGC is unsupported or initialization fails, native start returns an HRESULT
  (or `-4` for unsupported). The current application remains on the working
  `legacy_python` path. Borderless denial alone never fails capture.

## Build and test

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/build_native_engine.ps1
native\build\bin\Release\snowlink_capture_test.exe --monitor 0 --seconds 10
native\build\bin\Release\snowlink_capture_test.exe --monitor 1 --seconds 30 --cursor
```

The benchmark initializes D3D11/WGC, acquires AddRef'd GPU textures, counts new
frame IDs, and reports produced/observed frames, FPS, resolution, replaced
frames, pool recreations, border state, and cursor state. It never maps or copies
a frame to CPU.

Validation on 2026-08-09:

- Release DLL and `snowlink_capture_test.exe` compile successfully with VS 2022
  and Windows SDK 10.0.26100.
- The current automated execution desktop cannot start the Windows capture
  service (`0x80070424`, `ERROR_SERVICE_DOES_NOT_EXIST`), so live frame/FPS proof
  must be run in an interactive Windows desktop session with Screen Capture
  services available. The benchmark reports the startup HRESULT cleanly.

## Remaining problems

- Run and record the benchmark on an interactive physical/VM Windows desktop;
  the present automation session has no WGC capture service.
- Complete production MSIX identity/signing/assets and restricted-capability
  submission before promising borderless capture in release builds.
- Wire the GPU latest-frame consumer into the later hardware encoder.
- Add orchestration retry/backoff for access/device loss after display topology
  settles.
- Native Desktop Duplication fallback is not implemented yet.

## Next phase

Next phase: implement DXGI Desktop Duplication backend.
