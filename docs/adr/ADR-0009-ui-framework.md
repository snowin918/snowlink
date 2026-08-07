# ADR-0009 — UI framework

- **Status:** Accepted
- **Date:** 2026-08-06

## Decision

PySide6 with a dedicated asyncio thread and Qt signals (not qasync in MVP).

## Consequences

Capture and networking stay off the UI thread; careful shutdown coordination required.
