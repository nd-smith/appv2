# Phase 1: Foundation — Implementation Plan

**Date:** 2026-03-18
**Status:** In Progress

## Objective

Establish core plumbing for a single source (claimx) flowing end-to-end: Event Hub → Bridge Worker → Kafka Internal Topic → Transform Worker → Kafka Target Topic, with structured logging to a Kafka logging topic and HTTP health endpoints on all workers.

## Technology Choices

| Component | Choice | Decision Record |
|---|---|---|
| Concurrency | Sync + threaded health server | [0001](../decisions/0001-sync-with-threaded-health.md) |
| Kafka client | confluent-kafka | [0002](../decisions/0002-confluent-kafka-client.md) |
| Logging | structlog (JSON → Kafka) | [0003](../decisions/0003-structlog-for-logging.md) |
| Data models | stdlib dataclasses | [0004](../decisions/0004-dataclasses-for-contracts.md) |
| Python | 3.12 |
| Package manager | uv |
| Config | PyYAML + dataclasses |
| Testing | pytest, Redpanda (docker-compose) |
| Linting | ruff |

## Milestones

### 1. Project Skeleton
- pyproject.toml with all dependencies
- Directory structure (src/pipeline, tests, schemas, deploy)
- docker-compose.yaml with Redpanda
- ruff configuration

### 2. Core Contracts
- Message envelope dataclass (`src/pipeline/envelope.py`)
- Structured log event + structlog config (`src/pipeline/logging.py`)
- Config dataclasses + YAML loader (`src/pipeline/config.py`)
- Unit tests for all three

### 3. Infrastructure Wrappers
- Kafka producer wrapper (`src/pipeline/kafka_producer.py`)
- Kafka consumer wrapper (`src/pipeline/kafka_consumer.py`)
- Event Hub consumer wrapper (`src/pipeline/eventhub_consumer.py`)
- Health server (`src/pipeline/health.py`)
- Unit tests with mocked clients

### 4. Base Worker Framework
- Base worker class (`src/pipeline/workers/base.py`)
- Lifecycle: init → setup → start → run_loop → shutdown
- Signal handling (SIGTERM/SIGINT)
- Health server integration

### 5. Bridge Worker
- Event Hub → envelope creation → Kafka produce (`src/pipeline/workers/bridge.py`)
- Entrypoint: `python -m pipeline.workers.bridge`

### 6. Passthrough Transform Worker
- Kafka consume → update envelope → Kafka produce (`src/pipeline/workers/transform.py`)
- Entrypoint: `python -m pipeline.workers.transform`

### 7. Integration & E2E Tests
- Integration tests against Redpanda
- E2E: bridge → internal topic → transform → target topic
- Logging topic verification

### 8. Deployment Artifacts
- Multi-stage Dockerfile
- K8s manifests for bridge and transform workers

## Config (config.yaml)

Single source (claimx) with Event Hub ingestion, internal Kafka topic, target Kafka topic, and retry configuration. Environment variable substitution for secrets.

## Exit Criteria

- Message enters via Event Hub, flows through bridge → internal topic → transform → target topic
- Every step emits structured JSON log to logging topic
- Complete log trace with all required fields (correlation_id, source_id, timestamp, worker_type, worker_id, stage, event_type, level)
- /healthz and /readyz endpoints on both workers
- Graceful shutdown on SIGTERM
- config.yaml drives all source configuration
- Unit and integration tests pass
