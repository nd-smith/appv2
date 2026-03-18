# CLAUDE.md — Multi-Source Streaming Data Pipeline

## Project Overview

A Python-based, multi-source streaming data pipeline for insurance claims processing. Upstream source systems (Xactanalysis, ClaimX, Validate, etc.) publish events to Azure Event Hub. Bridge workers consume from Event Hub and re-broadcast to Kafka, which serves as the internal and output transport. Transform workers enrich messages and produce to target Kafka topics for downstream consumers (Spark jobs, etc.).

**Key constraint:** This is an ops-heavy system maintained by non-Python-specialists. Observability, simplicity, and traceability are paramount. Every design decision must pass the KISS test.

## Architecture at a Glance

```
Source Event Hubs → Bridge Workers → Kafka Ingestion Topics → Transform Workers → Kafka Target Topics
                                                                      ↓
                                                              Rules Engine → Side-Effect Kafka Topics
                                                              Attachments → S3 Download/Upload
                                                                      ↓
                              All Workers → Structured Logs → Logging Kafka Topic → KQL DB
```

**Two transports only:** Azure Event Hub (ingestion from sources) and Kafka (everything else — internal, output, logging, dead-letter, side-effects). No other transports.

## Tech Stack

- **Language:** Python
- **Infrastructure:** Kubernetes, Azure Event Hub, Apache Kafka
- **Storage:** S3 (attachment handling)
- **Validation:** JSON Schema
- **Configuration:** YAML (config.yaml, rules_config.yaml)
- **Observability:** Structured JSON logs → Kafka logging topic → KQL DB

## Repository Structure

Monorepo. Single repo, single CI/CD pipeline. All source configs, shared framework code, transforms, schemas, and deployment config live here. No published packages, no cross-repo versioning.

Two top-level config files:
- `config.yaml` — source system definitions (the single source of truth for sources)
- `rules_config.yaml` — side-effect rules (separate from source config intentionally)

## Design Principles (Non-Negotiable)

1. **Simplicity is king.** If a simpler approach covers 90% of cases, prefer it. Do not over-engineer for hypothetical future requirements.
2. **Dual-transport architecture.** Event Hub for ingestion, Kafka for everything else. No exceptions.
3. **Observability for non-experts.** Any message's lifecycle must be reconstructable from logs alone.
4. **Shared infrastructure, separated execution.** Infra is shared (networking, Event Hub namespaces, Kafka cluster). Compute and config are separated per source for clarity, not security.
5. **Pipeline is not the analytical store.** The pipeline's product is an enriched message on a target Kafka topic. Persistence is downstream's job.

## Worker Types

All workers are independent K8s deployments. All expose `/healthz` (liveness) and `/readyz` (readiness) HTTP endpoints. Health server runs alongside — never inside — the main event loop.

### Bridge Workers (Event Hub → Kafka)
- **Event Hub consumers:** Primary pattern. Consume from source Event Hubs, assign correlation ID (UUID v4), wrap in envelope, produce to internal Kafka topic.
- **Push receivers:** HTTP/webhook endpoints accepting incoming events.
- **Pull pollers:** Poll source APIs/CDC streams on a schedule.

### Transform/Enrichment Workers
- Consume from internal Kafka topics, apply source-specific logic, produce to target topics.
- Handle attachments (S3 download/upload) when configured.
- Evaluate side-effect rules after each stage.

### Output Workers
- Read from final processing stage, write enriched messages to target Kafka topics with full envelope.

## Critical Contracts

### Message Envelope
Every message must carry: `correlation_id`, `source_event_id`, `source_id`, `schema_version`, `ingested_at`, `processed_at`, `transforms_applied`, `attachments`, `payload`.

### Structured Log Events
All logs are JSON to the Logging Kafka topic. Required fields: `correlation_id`, `source_id`, `timestamp` (ISO 8601 UTC), `worker_type`, `worker_id` (pod name), `stage`, `event_type`, `level`, `detail`.

### Correlation ID
UUID v4, assigned at ingestion, immutable, present on every log event, inter-stage message, and output message. This is the primary key for tracing.

## Error Handling

- **Retry:** Exponential backoff. Defaults: 3 retries, 1s initial, 30s max, 2x multiplier. Configurable per source. Every retry emits WARN log.
- **Dead-letter:** Shared Kafka topic. Includes original payload, correlation_id, source_id, failure reason, stage, timestamp, worker_id. Never silently drop. Always emit ERROR log.
- **Poison messages:** Consecutive failure counter → dead-letter. Keep it simple.
- **Backpressure:** Alert-and-pause. Stop consuming, mark /readyz non-200, periodically re-check, resume when target recovers. No local queuing.

## Schema Validation

- Validates at bridge layer, before producing to internal Kafka.
- JSON Schema files stored in monorepo alongside config.
- Failed validation → immediate dead-letter with validation error details.
- Not bypassable in production.
- Additive changes (new optional fields) pass without schema updates.
- Breaking changes use temporary dual-schema window (max 14 days).

## Side-Effect Rules Engine

- Defined in `rules_config.yaml` (separate from `config.yaml`).
- Each rule: name, source filter, stage to evaluate at, condition, target Kafka topic.
- Evaluated after each pipeline stage completes.
- Each side effect gets its own dedicated Kafka topic.
- Keep rules simple: equality, presence, pattern matching. Complex logic belongs in transforms.
- Failed side-effect emits do NOT block the main pipeline — dead-letter independently.

## Attachment Handling

- Triggered by attachment URL field configured per source in `config.yaml`.
- Download from pre-signed S3 URL → temp local file → upload to configured destination → update message with stored_path (preserve original URL) → delete temp file.
- Expected size: 10–100 MB. Download to disk, upload from disk. No streaming through memory.
- Subject to standard retry policy. Failure → dead-letter entire message.

## Phased Implementation

### Phase 1: Foundation
Core plumbing. Single source, end-to-end streaming, logging, health.
- Monorepo structure + shared framework
- Base worker framework with health endpoints
- Bridge worker (Event Hub consumer → Kafka)
- Passthrough transform worker
- Structured logging to Kafka
- Message envelope contract
- **Exit:** One source flows end-to-end with complete log trace.

### Phase 2: Transform Engine, Attachments, Rules
Source-specific enrichment, attachments, rules, error handling.
- Source-specific transforms (start parameterized)
- Attachment download/upload
- Rules engine (rules_config.yaml)
- Schema validation (JSON Schema)
- Dead-letter flow
- Retry + exponential backoff
- Poison message detection
- **Exit:** Messages validated, transformed, attachments handled, rules firing, failures dead-lettered.

### Phase 3: Multi-Source
Scale to many sources with separated compute and config.
- config.yaml-driven source definitions
- Pull-based ingestion workers
- Per-source worker deployments
- Source isolation verification
- Onboarding runbook
- **Exit:** Multiple sources running simultaneously with documented onboarding.

### Phase 4: Hardening
Production readiness.
- Load testing
- Failure scenario testing
- Operator documentation and runbooks
- Alerting rules
- Performance baselines
- **Exit:** Sustained load, graceful recovery, operator self-service via logs and runbooks.

## Coding Guidelines

- **Do not build Phase N+1 abstractions during Phase N.** Solve the current problem simply. Refactor only when the next phase demands it.
- **No custom module system until a source actually needs it.** Start with parameterized config for transforms.
- **Consumer groups:** Every worker gets its own dedicated consumer group. Use clear, consistent naming.
- **Adding a source should require:** config.yaml entry + schema file + optional custom transform + deploy. No shared infrastructure code changes.
- **Source scale:** Designed for <50 sources. No dynamic orchestration needed.
- **Schema changes deploy via CI/CD.** No hot-reload. Every change is a git commit with review trail.

## Decision Log

All significant design and implementation decisions must be documented in `docs/decisions/`. This serves as an audit trail so anyone can understand *why* the system works the way it does.

**Process:**
1. Before implementing a decision, compare it against the PRD (`PRD/prd_pipeline.md`) to confirm alignment or explicitly note any deviation.
2. Create a new markdown file in `docs/decisions/` named `NNNN-short-description.md` (zero-padded sequential number, e.g., `0001-use-kafka-for-dead-letter.md`).
3. Use this template:

```markdown
# NNNN: Decision Title

**Date:** YYYY-MM-DD
**Status:** Accepted | Superseded by NNNN | Deprecated

## Context
What problem or question prompted this decision?

## Decision
What was decided?

## PRD Alignment
How does this align with the PRD? If it deviates, explain why.

## Consequences
What are the trade-offs? What becomes easier or harder?
```

**Rules:**
- Every decision that affects architecture, contracts, error handling, transport, or worker behavior gets an entry.
- Decisions that deviate from the PRD must explicitly document the rationale for deviation.
- Decisions are append-only — never edit a past decision. If a decision is reversed, create a new entry that supersedes the old one.
- Keep entries concise. The goal is traceability, not prose.

## Reference

- Full PRD: `PRD/prd_pipeline.md`
- Decision log: `docs/decisions/`
