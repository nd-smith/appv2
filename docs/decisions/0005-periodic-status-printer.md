# 0005: Periodic Status Printer for Worker Observability

**Date:** 2026-03-20
**Status:** Accepted

## Context
Operators rely on `kubectl logs` (stdout) to understand worker state. Prior to this change, stdout only showed ERROR/CRITICAL JSON events — healthy workers were silent. There was no way to tell at a glance whether a worker was alive, processing, or stuck without accessing K8s APIs or Kafka directly.

## Decision
Add a `StatusPrinter` daemon thread to `BaseWorker` that periodically prints a plain-text status summary to stdout. Track simple counters (`messages_processed`, `errors`, `started_at`, `last_message_at`) on `BaseWorker`, protected by a `threading.Lock` for thread safety with the bridge worker's Event Hub callback thread.

Output is plain text, visually distinct from the JSON structured logs:
```
--- STATUS [bridge/claimx @ pod-xyz] uptime=2h 14m 33s ---
  messages: 1,247 | errors: 3 | rate: 9.2 msg/min | last msg: 12s ago
--------------------------------------------------------------
```

Interval defaults to 60 seconds, configurable via `--status-interval` CLI argument or `STATUS_INTERVAL_SECONDS` environment variable.

## PRD Alignment
The PRD requires "Observability for non-experts" and that "Any message's lifecycle must be reconstructable from logs alone." This feature directly supports operational observability without adding complexity — no metrics framework, no config.yaml changes, no changes to the structured logging contract.

## Consequences
- **Easier:** Operators can immediately see worker health from stdout. No tooling required beyond `kubectl logs`.
- **Harder:** Stdout now mixes plain-text status lines with JSON structured logs. Log parsers that expect pure JSON on stdout will need to handle or filter these lines.
- **Trade-off:** Simple total/uptime rate calculation rather than windowed rates. Sufficient for operational awareness; detailed metrics belong in a future metrics system if needed.
