# ADR-0005 — System audio capture

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

PyAudioWPatch WASAPI loopback for system audio (not microphone). Opus @ 48 kHz, 20 ms frames.

## Consequences

Endpoint hotplug and DRM silence must be documented; restart share on device change.
