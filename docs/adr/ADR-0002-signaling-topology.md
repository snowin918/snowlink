# ADR-0002 — Signaling topology

- **Status:** Accepted
- **Date:** 2026-08-06

## Context

Peers need a simple offline way to exchange SDP/ICE without cloud relays.

## Decision

The sharing computer runs a WebSocket signaling server bound to the selected LAN IPv4. The viewing computer dials `ws://<ip>:<port>/ws`.

## Consequences

- Single inbound TCP hole on the sharer
- Firewall/VPN LAN blocks must be diagnosed explicitly
- Matches "enter IP + port" UX
