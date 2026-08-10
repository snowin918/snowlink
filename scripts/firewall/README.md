# Firewall helpers (manual)

Snowlink never disables VPN security or silently installs firewall rules.

On first listen, accept the Windows Firewall prompt for `Snowlink.exe`.

The native media engine uses UDP ports `40000-40100` on both peers. This fixed
range avoids unpredictable ephemeral-port behavior while a VPN is active.

From an elevated PowerShell prompt, install narrowly scoped Private/LAN rules:

```powershell
.\scripts\firewall\allow_snowlink.ps1
```

For a copied portable build, provide its executable explicitly:

```powershell
.\scripts\firewall\allow_snowlink.ps1 -Executable "C:\Apps\Snowlink\Snowlink.exe"
```

If connect hangs with VPN enabled, enable **Allow local network / LAN** in the VPN
client and re-run Diagnostics → Connectivity. See `docs/vpn-lan-access.md`.

Example **operator-run** query (read-only):

```powershell
netsh advfirewall firewall show rule name=all dir=in | findstr /i Snowlink
```
