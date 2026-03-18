# 0003: structlog for Structured Logging

**Date:** 2026-03-18
**Status:** Accepted

## Context
The PRD requires structured JSON logs with mandatory fields (correlation_id, source_id, timestamp, worker_type, worker_id, stage, event_type, level, detail) sent to a Kafka logging topic. Need a logging library that supports context binding and JSON output.

## Decision
Use `structlog` for all application logging. Configure it to output JSON and bind context variables (correlation_id, source_id, worker_type, worker_id) that persist across log calls within a processing scope.

## PRD Alignment
Directly implements "Structured JSON logs → Kafka logging topic → KQL DB" and all required log fields. Context binding ensures correlation_id flows through every log event without manual passing, supporting the PRD's "Any message's lifecycle must be reconstructable from logs alone" requirement.

## Consequences
- **Easier:** Context binding eliminates boilerplate — bind correlation_id once per message, all subsequent logs include it. JSON rendering is built-in. Processor pipeline allows adding timestamp formatting, level normalization.
- **Harder:** structlog's processor chain model has a learning curve, but configuration is done once and doesn't change.
- **Trade-off:** Adds a dependency beyond stdlib logging, but structlog is lightweight and widely adopted. The alternative (stdlib logging with custom JSON formatter) would require more custom code for context binding.
