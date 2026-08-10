# Snowlink Native Engine Progress

## Architecture

Snowlink keeps the PySide6 / Python application for UI, settings, login/device list
(future), session orchestration, pairing, and configuration.

High-frequency media work moves into a native C++ engine (`native/`) that owns:

```
PyQt / Python application
        |
        | small control API (C ABI DLL + ctypes)
        v
Native C++ Snowlink Engine
        |
        +-- Capture
        |    +-- Windows.Graphics.Capture   (next phase)
        |    +-- DXGI Desktop Duplication   (later)
        |
        +-- D3D11 GPU processing
        +-- Hardware video encoder
        +-- Native network/media transport
        +-- Native decoder
        +-- D3D11 renderer
        +-- Cursor subsystem
        +-- Input subsystem
```

**Hard boundary:** uncompressed video frames never cross into Python.
The intended hot path is `Capture → D3D11 → encoder → transport` entirely in native code.
Python issues commands and receives events / statistics only.

Two selectable **media engines** (orthogonal to the existing DXcam capture backend
`dxgi` / `winrt`):

| Preference value   | Meaning |
|--------------------|---------|
| `legacy_python`    | Current DXcam + aiortc / PyAV pipeline (default, fully working). |
| `native_cpp`       | Native engine foundation. Init/shutdown/stats work; streaming not wired yet. Sessions still run on `legacy_python`. |

## Existing Python Reference

| Area | Path | Role today |
|------|------|------------|
| Screen capture | `src/snowlink/media/screen_capture.py` | DXcam DXGI (default) / WinRT; `LatestFrameSlot` |
| Capture models | `src/snowlink/media/capture_models.py` | Presets, `dxgi`/`winrt` backend names |
| Video track / encode prep | `src/snowlink/media/video_track.py` | BGR → PyAV `yuv420p` for aiortc |
| Encode / decode | aiortc + PyAV | Software VP8 (no first-party encoder/decoder) |
| Share/view session | `src/snowlink/rtc/screen_session.py` | End-to-end WebRTC session |
| Peer connection | `src/snowlink/rtc/peer_connection.py` | Host ICE, VP8/Opus prefs |
| Viewer frames | `src/snowlink/rtc/preview.py` | Decode drain → BGR for Qt |
| Signaling | `src/snowlink/net/signaling_server.py`, `signaling_client.py` | Sharer-hosted WebSocket |
| Cursor | `screen_capture.resolve_cursor_policy` | WinRT env knob; DXGI unsupported |
| Remote input | *(none)* | Out of MVP; native `IInputSubsystem` stub reserved |
| UI integration | `src/snowlink/ui/share_controller.py`, `workers.py`, `pages/*` | PySide6 control plane |
| Packaging | `packaging/snowlink-gui.spec`, `scripts/dev/build_gui_exe.py` | PyInstaller onedir |

## Native Files

Created in this phase:

```
native/CMakeLists.txt
native/include/snowlink/
  types.h, engine.h, capture.h, encoder.h, decoder.h,
  renderer.h, transport.h, cursor.h, input.h, c_api.h
native/src/
  engine.cpp, c_api.cpp
  capture/capture_manager.cpp
  encode/encoder.cpp
  decode/decoder.cpp
  render/renderer.cpp
  transport/transport.cpp
  cursor/cursor.cpp
  input/input.cpp
  common/factories.h, status_util.h
scripts/dev/build_native_engine.ps1
src/snowlink/native_engine/
  __init__.py, backend.py, loader.py, engine.py
docs/native-engine-progress.md
tests/unit/test_native_engine_backend.py
tests/unit/test_native_engine_lifecycle.py
```

Also updated: `src/snowlink/config.py` (`media_engine`), `config/default.toml`,
`src/snowlink/ui/pages/settings.py` (Media engine combo), `.gitignore`,
`tests/unit/test_config.py`.

## Build

Requirements: Visual Studio 2022 (MSVC), Windows 10/11 SDK, CMake (VS-bundled is fine).

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/build_native_engine.ps1
```

Or manually:

```powershell
$cmake = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
& $cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
& $cmake --build native/build --config Release
```

Output DLL (typical):

`native/build/bin/Release/snowlink_engine.dll`

Optional override for the Python loader:

```powershell
$env:SNOWLINK_ENGINE_DLL = "C:\path\to\snowlink_engine.dll"
```

Verify from Python (with `src` on `PYTHONPATH` or editable install):

```powershell
python -c "from snowlink.native_engine import probe_native_engine; print(probe_native_engine())"
```

## Completed

- Native CMake/MSVC project builds `snowlink_engine.dll` (C++20).
- Public C++ subsystem interfaces + engine lifecycle (`initialize` / `shutdown`,
  control setters, `get_stats`).
- Stable C ABI (`snowlink/c_api.h`) for Python.
- Python ctypes wrapper (`snowlink.native_engine`) — control/status only.
- `media_engine` preference: `legacy_python` | `native_cpp` (default legacy).
- Settings UI exposes Media engine without changing Share/View behavior.
- Existing Python media path untouched and still the production session backend.
- D3D11 / DXGI / Media Foundation / `windowsapp` linked so the SDK surface is ready.

## Not Implemented

- Windows.Graphics.Capture (native)
- DXGI Desktop Duplication (native)
- D3D11 frame processing / scaling
- Hardware encoder / decoder
- Native media transport / packetization
- D3D11 renderer
- Cursor compositing in native code
- Remote input injection
- Replacing aiortc session path with native streaming
- Shipping the DLL inside the PyInstaller bundle (next packaging phase)

`start_capture` / `start_stream` / `request_keyframe` return `SNOWLINK_ERR_NOT_IMPLEMENTED`
by design in this foundation build.

## Important Decisions

1. **Interface choice:** stable **C ABI DLL + ctypes**, not pybind11. Matches existing
   Win32 ctypes usage and keeps PyInstaller packaging simple (`snowlink_engine.dll`
   beside the exe later).
2. **No frames to Python.** Never: GPU frame → Python → encoder.
3. **`media_engine` ≠ capture `backend`.** `backend` remains `dxgi`/`winrt` for the
   legacy DXcam path. `media_engine` selects legacy vs native pipeline.
4. **Sessions stay on legacy** until native capture + encode + transport are real.
   Selecting `native_cpp` only enables probing the native lifecycle.
5. **Preserve Python media code** as the behavioral reference; do not delete it.
6. **RAII / ComPtr:** prefer `std::unique_ptr` and (in later phases)
   `Microsoft::WRL::ComPtr` / C++/WinRT for COM and WinRT objects.
7. **Stats** are cheap counters/gauges — no per-frame logging across the FFI.

## Next Phase

Next phase: implement Windows.Graphics.Capture native backend.

## Definition of done

This phase is complete when:

- Native C++ project builds successfully.
- Snowlink still launches without regressions.
- Native engine initialization is invokable from Python.
- Native engine can cleanly initialize and shutdown.
- No screen capture has been migrated yet unless trivial initialization is required.
- Existing Python media behavior remains intact.
