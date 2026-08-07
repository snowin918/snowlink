# ADR-0008 — Pairing security

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

6-digit code + on-sharer Approve/Deny + per-session secret + TTL + rate limits + one viewer.

## Consequences

Brute-force window exists on hostile LAN; mitigated by TTL, rate limit, and human approval.
