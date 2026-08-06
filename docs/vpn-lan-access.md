# VPN and LAN access (Experiment B)

Snowlink is designed for **two Windows 11 PCs on the same physical LAN**.
Both machines may also run VPN clients. VPN virtual adapters, kill switches, and
Windows Firewall often break naïve “bind everything / use the default route”
designs.

**Snowlink does not disable, bypass, or reconfigure VPN security settings or
Windows Firewall policy.** This document explains how to *measure* LAN TCP
reachability (Experiment B) and how to interpret failures. For organization-
managed VPNs that prohibit local LAN access, contact your administrator — do
not attempt to circumvent workplace, school, or managed security controls.

---

## 1. Purpose of Experiment B

Experiment B verifies whether Computer B can complete a **TCP echo** to a
listener bound to Computer A’s **selected physical LAN IPv4** with **both VPNs
on** (`vpn-on-on` — the only required Phase 0 network scenario). The echo is a
stand-in for later signaling TCP (not media).

ICMP ping is optional and **never** sufficient alone.

---

## 2. Required setup on both computers

1. Windows 11 on both PCs.
2. Python 3.12+ venv with the Snowlink repo installed (`pip install -r requirements-dev.txt`).
3. Both PCs on the **same physical LAN** (same subnet or otherwise routable on the LAN).
4. Ability to approve a Windows Firewall prompt for Python **if** you intend to
   allow inbound Experiment B traffic (user choice; Snowlink never adds rules).
5. Experiment A working (`list` / local `serve`+`connect`).

---

## 3. Identify each physical LAN IPv4

On **each** computer:

```powershell
python experiments/experiment_a_adapter_bind.py list
```

Select an adapter marked **PREFERRED** (`physical_ethernet` or `physical_wifi`)
with a private IPv4 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).

Avoid for the primary path: VPN/tunnel, Hyper-V, WSL, Tailscale/mesh, loopback.

Example: Computer A = `192.168.1.25`, Computer B = `192.168.1.30`.

---

## 4. Start the server (Computer A)

```powershell
python experiments/experiment_b_two_machine_tcp.py serve `
  --ip 192.168.1.25 `
  --port 3847 `
  --session-name vpn-off-off `
  --serve-forever
```

Confirm the printed line:

```text
Listening on 192.168.1.25:3847 (getsockname)
```

The bound address must equal the selected LAN IP (not `0.0.0.0`).

---

## 5. Run the client (Computer B)

```powershell
python experiments/experiment_b_two_machine_tcp.py connect `
  --ip 192.168.1.25 `
  --port 3847 `
  --session-name vpn-off-off `
  --source-ip 192.168.1.30 `
  --timeout 5
```

Exit code **0** only when the echo is verified. JSON results are written under
`experiment-results/experiment-b/` (gitignored).

---

## 6. Four VPN test scenarios

| `--session-name` | Computer A VPN | Computer B VPN |
| --- | --- | --- |
| `vpn-off-off` | Off | Off |
| `vpn-on-off` | On | Off |
| `vpn-off-on` | Off | On |
| `vpn-on-on` | On | On |

Do not rely on automatic VPN detection. Toggle VPNs manually, then run serve
and connect with the matching `--session-name`.

Print instructions anytime:

```powershell
python experiments/experiment_b_two_machine_tcp.py guide
```

---

## 7. Using `--source-ip`

`--source-ip` binds the **client** socket to a local IPv4 before `connect`.

Use Computer B’s physical LAN address so the OS does not source the connection
from a VPN adapter. If bind fails, the client **fails clearly** — it does not
silently fall back to another address.

After connect, the result records `getsockname()` as `actual_source_ip` /
`actual_source_port`.

---

## 8. Interpreting common errors

### Connection refused (`CONNECTION_REFUSED`)

Likely: nothing listening on that IP:port; server bound a different address;
an active refuse from a filter.

**Next:** Confirm Computer A still shows `Listening on <A-LAN-IP>:3847`.

### Connection timeout (`CONNECTION_TIMEOUT`)

Likely causes (not certainties):

- Windows Firewall blocked the inbound connection.
- The VPN client blocks local LAN traffic.
- The wrong physical LAN IP was selected.
- The server is not listening on the expected address.

**Next:** Re-check IPs, firewall prompt history, and VPN “Allow LAN” style options.
Do not disable managed protections.

### Network / host unreachable

Likely: routing table / VPN changed routes so the LAN path is gone.

**Next:** Confirm both still have LAN IPv4s on the same network; review VPN
split-tunnel / LAN settings with an administrator if managed.

### Wrong source IP

The client connected but `actual_source_ip` is a VPN address.

**Next:** Pass `--source-ip` with the physical LAN IPv4 from Experiment A `list`.

### Successful TCP but failed echo (`ECHO_MISMATCH` / `SERVER_CLOSED`)

Likely: wrong process on the port, or the server exited mid-transfer.

**Next:** Ensure only Experiment B `serve` owns that port; retry with server kept up.

---

## 9. Windows Firewall troubleshooting

1. On first listen, Windows may prompt to allow Python — choose Private networks
   if you intend local LAN testing.
2. If no prompt appeared and connects time out, check Windows Security → Firewall
   → Allowed apps (manual review only).
3. Snowlink **does not** create or modify firewall rules automatically.
4. Optional operator-run `netsh` examples may appear later under `scripts/firewall/`;
   they are never executed by the app.

---

## 10. Common VPN setting names

Clients use different labels for the same ideas. Look for options such as:

- Allow LAN access
- Allow local network
- Local network sharing
- Block connections without VPN
- Kill switch
- Split tunneling

Enabling “allow LAN / local network” (when your policy permits) often restores
peer-to-peer LAN TCP while the VPN stays connected. **Kill switch** / “block
without VPN” modes may intentionally block LAN — that is a security feature,
not a Snowlink bug.

For **managed** VPNs: if local LAN access is prohibited, contact the
administrator. Do not bypass organization policy.

---

## 11. Snowlink policy statement

Snowlink will:

- Select and bind to a user-visible LAN IPv4.
- Prefer physical adapters and deprioritize VPN/virtual adapters.
- Surface diagnostics and likely causes.

Snowlink will **not**:

- Disable or bypass VPN kill switches.
- Change VPN configuration.
- Silently modify Windows Firewall policy.
- Require Administrator rights to “defeat” VPN security.

---

## 12. Result-recording template

Required gate row is **vpn-on-on** only.

| Scenario | A VPN | B VPN | A LAN IP | B source IP | Success | Error code | Connect ms | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vpn-on-on | On | On | 192.168.139.20 | 192.168.139.20 | yes | | 25 | Same-host LAN bind under Astrill; confirm two-PC in ops |

Also keep the JSON files under `experiment-results/experiment-b/`.

Summarize:

```powershell
python experiments/experiment_b_two_machine_tcp.py summarize `
  --results-dir experiment-results/experiment-b
```

---

## 13. Pass and fail criteria

| Check | Pass | Fail |
| --- | --- | --- |
| Required `vpn-on-on` | Echo OK; source/dest are physical LAN IPs | Cannot connect with both VPNs on |
| Bind address | `getsockname()` equals selected A LAN IP | Bound to `0.0.0.0` or wrong IP |
| Source bind | `actual_source_ip` equals `--source-ip` | VPN source used despite `--source-ip` |
| Security | No VPN/firewall settings changed by Snowlink | Any automated bypass |

---

## Related commands

```powershell
python experiments/experiment_b_two_machine_tcp.py guide
python experiments/experiment_a_adapter_bind.py list
```
