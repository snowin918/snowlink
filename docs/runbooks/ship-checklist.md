# Ship checklist — portable onedir MVP

## Build

```powershell
pip install -e ".[dev,ui,capture,audio,webrtc]"
python scripts/dev/build_gui_exe.py
```

Artifact: `packaging/dist/Snowlink/` (entire folder).

## Clean VM smoke

- [ ] Launch `Snowlink.exe` without a Python venv
- [ ] Home / Share / View / Diagnostics / Settings navigate
- [ ] Diagnostics Connectivity checklist runs (bind + handshake on selected IP)
- [ ] Share → View on two PCs with pairing Approve
- [ ] First-listen Windows Firewall prompt accepted (or documented manual rule)
- [ ] If PyAV fails: VC++ redistributable dialog appears

## Firewall

Do **not** silently add rules. Prefer the Windows first-run prompt.
Manual examples (operator-run only) may live under `scripts/firewall/` later.

## Distribution notes

- Prefer **no Administrator** for normal use
- Signed installer is Phase 5 — MVP ships portable onedir
- Config/logs: `%LOCALAPPDATA%\Snowlink\`
