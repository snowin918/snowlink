# ADR-0003 — ICE / VPN path selection

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

No STUN/TURN in MVP (`iceServers = []`). Prefer host candidates on the selected NIC IP; filter SDP host candidates via `snowlink.rtc.ice_policy`.

## Consequences

- Stays on LAN; avoids VPN default routes
- Mis-selected adapters still require manual override
