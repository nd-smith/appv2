# 0001: Sync Concurrency Model with Threaded Health Server

**Date:** 2026-03-18
**Status:** Accepted

## Context
Workers need a concurrency model for their main event loop and must expose HTTP health endpoints (`/healthz`, `/readyz`) alongside the main processing loop. Options considered: async (asyncio), sync with threaded health, full threading.

## Decision
Use synchronous Python for all worker logic. Run the HTTP health server in a daemon thread alongside the main event loop.

The main loop is a simple `while running: poll → process → produce` cycle. The health server is a stdlib `http.server.HTTPServer` started in a daemon thread before the main loop begins.

## PRD Alignment
Directly implements the PRD requirement: "Health server runs alongside — never inside — the main event loop." The daemon thread model satisfies "alongside" while keeping the main loop synchronous and simple.

## Consequences
- **Easier:** Debugging, reasoning about control flow, onboarding non-Python ops staff. No async/await complexity.
- **Harder:** If we later need concurrent I/O (e.g., parallel attachment downloads), we'd need to introduce threading or asyncio for that specific case.
- **Trade-off:** Daemon thread dies with the process — no cleanup needed, but also no graceful health server shutdown. Acceptable since health endpoints are stateless.
