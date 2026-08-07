# ADR-0007 — Audio codec / clock

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

Opus @ 48 kHz; audio-primary A/V sync on the receiver (`AvSyncController` + `av_skew_ms`).

## Consequences

Video may drop to stay near the audio playhead; long-session drift monitored via stats.
