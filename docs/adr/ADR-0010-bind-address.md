# ADR-0010 — Bind address default

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

Bind signaling to the selected IPv4, not `0.0.0.0`.

## Consequences

Predictable LAN path; wrong adapter selection is user-visible and overridable.
