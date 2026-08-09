# Ship checklist — portable onedir MVP

## Build

```powershell
pip install -e ".[dev,ui,capture,audio,webrtc]"
python scripts/dev/build_gui_exe.py
```

Artifact: `packaging/dist/Snowlink/` (entire folder).  
Optional zip: `packaging/dist/Snowlink-MVP-portable.zip`.

Evidence log: [`mvp-ship-evidence.md`](mvp-ship-evidence.md).

## Clean VM smoke

- [x] Build onedir (see `mvp-ship-evidence.md` for dated rebuild)
- [x] Launch `Snowlink.exe` without a Python venv (local host smoke — see evidence)
- [x] Clean Win11 VM: Home / Share / View / Diagnostics / Settings navigate
- [x] Diagnostics Connectivity checklist runs (bind + handshake on selected IP)
- [x] Share → View on two PCs with pairing Approve
- [x] First-listen Windows Firewall prompt accepted (or documented manual rule)
- [x] If PyAV fails: VC++ redistributable dialog appears

## Firewall

Do **not** silently add rules. Prefer the Windows first-run prompt.
Manual examples (operator-run only) may live under `scripts/firewall/`.

## Distribution notes

- Prefer **no Administrator** for normal use
- Signed installer is Phase 5 — MVP ships portable onedir
- Config/logs: `%LOCALAPPDATA%\Snowlink\`
- Mid-session monitor / audio-device changes: Stop Sharing, re-select device, Start Sharing again
