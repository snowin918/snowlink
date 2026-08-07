# Installer notes (MVP)

MVP distribution is **PyInstaller onedir** only:

```text
packaging/dist/Snowlink/Snowlink.exe
```

Ship the entire `Snowlink\` folder. A signed MSI/EXE installer is Phase 5.

## Native dependencies

- Bundle PyAV/FFmpeg via PyInstaller `collect_all("av")` when present in the build venv
- Bundle **PyAudioWPatch** via `collect_all("pyaudiowpatch")` — analysis alone may
  ship only `_portaudiowpatch*.pyd` and omit the importable package, which breaks
  system-audio share/view in the GUI build
- Build script installs `.[dev,ui,capture,audio,webrtc]` so those stacks are present
- On clean VMs, missing VC++ x64 redistributable may prevent `av` from loading —
  the GUI shows an actionable dialog

## First-run firewall

Windows may prompt to allow inbound TCP for signaling. Accept for private networks.
Never require Administrator to bypass VPN kill-switches.
