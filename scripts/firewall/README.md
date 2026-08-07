# Firewall helpers (manual)

Snowlink never disables VPN security or silently installs firewall rules.

On first listen, accept the Windows Firewall prompt for `Snowlink.exe`.

If connect hangs with VPN enabled, enable **Allow local network / LAN** in the VPN
client and re-run Diagnostics → Connectivity. See `docs/vpn-lan-access.md`.

Example **operator-run** query (read-only):

```powershell
netsh advfirewall firewall show rule name=all dir=in | findstr /i Snowlink
```
