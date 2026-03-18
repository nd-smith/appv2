# Product Requirements Document

**Multi-Source Streaming Data Pipeline**

Azure Event Hub · Kafka · Python · Kubernetes

Draft — March 2026

**Table of Contents**

# 1. Overview

## 1.1 Purpose

This document defines the product requirements for a multi-source, streaming data pipeline. Upstream source systems publish events to Azure Event Hub. A bridge worker consumes from these source Event Hubs and re-broadcasts messages to Kafka, which serves as the pipeline's internal and output transport. The pipeline integrates several upstream source systems used across the insurance claims lifecycle (e.g., Xactanalysis, ClaimX, Validate), applies source-specific enrichment and transformation logic, and produces enriched messages to designated target Kafka topics. Downstream consumers such as Spark jobs pick up the enriched data for storage and analytics.

## 1.2 Terminology

**Source system (or "source"):** An upstream system that produces events consumed by this pipeline. Examples: Xactanalysis, ClaimX, Validate. Each source system has its own configuration, schema, and potentially its own transform logic. Throughout this document, "source" refers to one of these integrated systems—not an external customer or tenant in the SaaS sense. This is one team managing multiple data integrations.

## 1.3 Design Principles

-   **Simplicity is king.** Every design decision should pass the KISS test (Keep It Simple, Stupid). If a simpler approach covers 90% of cases, prefer it over a complex approach that covers 100%. Resist the urge to over-engineer for hypothetical future requirements. Complexity is a cost that compounds over time and is paid by every person who maintains, debugs, or extends this system.

-   **Dual-transport architecture.** Azure Event Hub is the ingestion point where upstream source systems publish events. Kafka is the pipeline's internal bus—all inter-stage transport, logging, output, and side-effect routing flows through Kafka. A bridge worker connects the two: it consumes from source Event Hubs and produces to Kafka topics. There are no other transports.

-   **Observability for non-experts.** The pipeline will be maintained by operators who are not deep Python specialists. Logging, traceability, and health reporting must be comprehensive enough that any message's lifecycle can be reconstructed from logs alone.

-   **Shared infrastructure, separated execution.** Infrastructure is shared where it reduces operational burden (networking, Event Hub namespaces, Kafka cluster, logging). Compute and configuration are separated per source system primarily for code clarity, clean mental models, and independent lifecycle management—not as a strict security boundary.

-   **Pipeline is not the analytical store.** The pipeline's primary product is an enriched message on a target Kafka topic. Analytical persistence is the responsibility of downstream consumers. The pipeline does handle attachment storage (downloading and re-uploading files referenced in messages) as part of enrichment—see Section 9.

## 1.4 Scope

In Scope

-   Python-based streaming pipeline workers

-   Multi-source ingestion (push and pull patterns)

-   Source-specific and shared transformation/enrichment logic

-   Attachment handling: download from pre-signed S3 URLs, upload to configured storage

-   Bridge worker: Azure Event Hub consumer to Kafka producer

-   Structured logging to a dedicated logging Kafka topic

-   Per-message correlation ID traceability

-   Health endpoints (liveness and readiness) on all workers

-   Dead-letter and error handling strategy

-   Message schema validation

-   Source system onboarding via config.yaml

-   Side-effect rules engine with dedicated Kafka topics per side effect (rules_config.yaml)

Out of Scope

-   Kubernetes cluster provisioning and management

-   CI/CD pipeline infrastructure (deployed through an existing internal CI/CD system)

-   Downstream analytical storage and warehousing

-   Dashboard or UI for monitoring (the pipeline exposes data and endpoints; visualization is external)

# 2. Architecture

## 2.1 Repository Structure

The pipeline is a monorepo. All source system configurations, shared framework code, transform logic, schemas, and deployment config live in a single repository. One team owns this repo. One CI/CD pipeline deploys from it.

This keeps things simple: a single commit can add a new source system end-to-end (config, schema, transforms, deployment). Shared code (Event Hub wrappers, Kafka wrappers, logging, health endpoints, the message envelope) is imported directly—no published packages, no cross-repo versioning. The repo contains two top-level config files: config.yaml for source system definitions, and rules_config.yaml for side-effect rules.

## 2.2 High-Level Data Flow

The pipeline follows a linear streaming topology with fan-out capability. Azure Event Hub handles external ingestion; Kafka handles everything downstream:

**Source Event Hubs** (per-source or shared) → Bridge Workers → **Kafka Ingestion Topics** → Enrichment/Transform Workers → **Kafka Target Topics** (output)

A parallel logging stream runs alongside: every worker emits structured log events to a dedicated Logging Kafka topic. All messages carry a correlation ID from the moment of ingestion through final output.

## 2.3 Transport Topology

The pipeline uses two transport systems with a clear boundary between them:

### Azure Event Hub (Source Ingestion)

  **Hub Category**   **Ownership**            **Purpose**

  Source Hubs        Per-source or shared     Ingestion point for raw events from upstream source systems

Source Event Hubs are the only Azure Event Hub resources the pipeline consumes from. The bridge worker is the sole consumer of these hubs.

### Kafka (Internal and Output)

  **Topic Category**     **Ownership**            **Purpose**

  Internal Topics        Per-source or shared     Inter-stage transport between pipeline phases

  Target Topics          Per-source or shared     Enriched output messages for downstream consumers

  Logging Topic          Shared                   Structured pipeline trace logs and error events

  Dead-Letter Topic      Shared                   Messages that fail processing after retry exhaustion

  Side-Effect Topics     One per side effect      Dedicated topics for rule-triggered events, consumed by companion apps

All Kafka topics are managed by the pipeline team. Topic creation and configuration are part of the deployment process.

## 2.4 Consumer Group Policy

Every worker gets its own dedicated consumer group for each Kafka topic or Event Hub it consumes from. Use a clear, consistent naming convention so operators can tell at a glance what a consumer group belongs to.

## 2.5 Worker Types

The pipeline is composed of discrete worker types, each deployed as independent K8s deployments. Every worker type must expose HTTP health endpoints.

All worker types share one cross-cutting behavior: after each stage completes its primary work, it evaluates applicable side-effect rules from rules_config.yaml against the current message state. If a rule matches, a side-effect message is produced to that rule's designated Kafka topic. See Section 8 for details.

Bridge Workers

The bridge between Azure Event Hub and Kafka. Bridge workers consume raw events from source Event Hubs, assign a correlation ID, stamp the source ID, wrap the event in the standard message envelope, and produce to the appropriate internal Kafka topic. This is the only worker type that interacts with Azure Event Hub. Two sub-types:

-   **Push receivers:** HTTP/webhook endpoints that accept incoming events, assign a correlation ID, stamp the source ID, and produce to the appropriate internal Kafka topic.

-   **Pull pollers:** Workers that poll source systems (APIs, CDC streams, etc.) on a configured schedule, retrieve new events, assign correlation IDs, and produce to internal Kafka topics.

-   **Event Hub consumers:** Workers that consume from source Azure Event Hubs and re-broadcast messages to internal Kafka topics. This is the primary bridge pattern for source systems that publish to Event Hub.

Transform/Enrichment Workers

Consume from internal Kafka topics, apply source-specific logic, and produce enriched messages to target Kafka topics. Transforms can be as simple as source-specific config applied to a shared template, or as custom as a source-specific module implementing a defined interface. Start with the simplest approach that works for each source; don't build the custom module system until a source actually needs it.

This is also where attachment handling occurs—see Section 9.

Output Workers

Read from the final processing stage and write enriched messages to target Kafka topics. The output message includes the standard envelope (correlation ID, timestamps, transform metadata) so downstream consumers have full context without needing to query the logging topic.

# 3. Multi-Source Model

## 3.1 Separation Boundaries

Separation between source systems is an organizational choice for code clarity and operational sanity, not a security boundary. The following table summarizes where things are shared vs. separated:

  ———————-- —————- ——————————————————————————————————————
  **Dimension**           **Model**        **Rationale**

  Compute                 Separated        Per-source worker instances keep code and mental models clean, allow independent scaling, and simplify debugging

  Configuration / Logic   Separated        Each source has its own config entry and optional custom transform code, versioned together in the monorepo

  Event Hub Namespace     Shared           Shared namespaces for source hubs reduce operational overhead. Consumer groups provide logical separation

  Kafka Cluster           Shared           Single Kafka cluster for all internal and output topics. Consumer groups provide logical separation

  Logging                 Shared           Single logging Kafka topic; source_id on every log event enables filtering

  Networking              Shared           Common VNet/subnet; no per-source network separation needed
  ———————-- —————- ——————————————————————————————————————

## 3.2 Source Scale

The system is designed for a modest number of source systems (under 50). This permits per-source container deployments without dynamic orchestration. If the number of sources grows significantly, the architecture can be re-evaluated for worker pooling.

## 3.3 Source Configuration

All source system configuration lives in a config.yaml file within the monorepo. This file is the single source of truth for source definitions and is deployed through the standard CI/CD pipeline. No code changes to shared infrastructure should be required to add a source—only a new entry in config.yaml and a deploy.

**Each source entry in config.yaml must include:**

-   Unique source identifier (e.g., xactanalysis, claimx, validate)

-   Source Event Hub connection details (for Event Hub consumer bridge) and/or ingestion mode (push or pull)

-   Transform mode: parameterized config or custom module reference

-   Target Kafka topic designation

-   Attachment config: destination bucket/path and credentials reference (if applicable)

-   Pull schedule and retry policy (if applicable)

-   Schema reference for input validation

**Onboarding a new source:** Add the entry to config.yaml, add the schema file, optionally add custom transform code, commit, and deploy. The process should be documented as a runbook.

# 4. Logging and Traceability

This is the most operationally critical section of the system. The pipeline will be maintained by operators who need to diagnose issues, trace messages, and verify correctness without reading source code. The logging system must be comprehensive, structured, and self-explanatory.

## 4.1 Correlation ID

Every message receives a globally unique correlation ID at the moment of ingestion. This ID is immutable and must be present on every log event, every inter-stage message, and every output message associated with that original event. The correlation ID is the primary key for reconstructing an event's full lifecycle.

**Format:** UUID v4, assigned by the ingestion worker. If the source event already contains a unique identifier from the upstream system, the pipeline should store it as source_event_id alongside the pipeline's own correlation_id.

## 4.2 Structured Log Events

All log events are JSON-structured messages emitted to the Logging Kafka topic. Every log event must contain the following base fields:

  —————- ————— ——————————————————————————————————————————————————————————-
  **Field**        **Type**        **Description**

  correlation_id   string (UUID)   The message's pipeline-assigned correlation ID

  source_id        string          Source system this event belongs to (e.g., xactanalysis)

  timestamp        ISO 8601        UTC timestamp of the log event

  worker_type      string          bridge \| transform \| output

  worker_id        string          Unique identifier for the worker instance (pod name)

  stage            string          Pipeline stage name (e.g., ingest, validate, enrich, attachment, rules_eval, emit)

  event_type       string          message_received, validation_passed, validation_failed, transform_applied, attachment_downloaded, attachment_uploaded, rule_matched, emit_success, emit_failed, dead_lettered

  level            string          INFO, WARN, ERROR

  detail           object          Freeform JSON with event-specific context (errors, transform names, durations, attachment sizes, etc.)
  —————- ————— ——————————————————————————————————————————————————————————-

## 4.3 Logging Kafka Topic

A single dedicated Kafka topic receives all structured log events from all workers across all sources. The logging topic is ingested into a KQL database, which serves as the primary interface for operators querying traces and diagnosing issues. The pipeline does not own log retention or storage—that is managed by the KQL DB destination.

The logging topic should support the following consumption patterns:

-   KQL DB ingestion for queryable historical traces (primary consumer)

-   Real-time tailing for live debugging (operator consumer group)

-   Alerting integration (a consumer that watches for ERROR-level events and triggers notifications)

The source_id and correlation_id fields enable efficient filtering. Operators should be able to answer the question: "What happened to message X from Xactanalysis?" by querying the KQL DB alone.

## 4.4 Log Lifecycle of a Message

A healthy message should produce the following log sequence, reconstructable by correlation_id:

-   message_received — Bridge worker consumed the raw event from source Event Hub and assigned correlation_id

-   validation_passed — Schema validation succeeded

-   emit_success — Bridge worker wrote validated message to internal Kafka topic

-   message_received — Transform worker picked up the message from internal Kafka topic

-   transform_applied — One log per transform step (with transform name and version in detail)

-   rule_matched — If applicable: a side-effect rule fired (with rule name, target topic, and stage in detail)

-   attachment_downloaded — If applicable: file fetched from pre-signed URL (with size in detail)

-   attachment_uploaded — If applicable: file stored to destination (with path in detail)

-   emit_success — Transform worker wrote enriched message to target Kafka topic

Failed messages will show validation_failed, emit_failed, or dead_lettered events with full error context in the detail field.

# 5. Health and Operability

## 5.1 Health Endpoints

Every pipeline worker must expose the following HTTP health endpoints, compatible with Kubernetes probe configuration:

  ————— —————-- —————————————————————————————————————————————
  **Endpoint**    **K8s Probe**     **Behavior**

  /healthz        Liveness probe    Returns 200 if the process is alive. Failure triggers pod restart.

  /readyz         Readiness probe   Returns 200 if the worker can process events. Checks Event Hub and/or Kafka connectivity and config load status. Failure removes pod from service.
  ————— —————-- —————————————————————————————————————————————

Health endpoints must be served by a lightweight HTTP server that runs alongside the main event processing loop, not within it. A blocked event loop must not prevent health responses.

## 5.2 Readiness Checks

The /readyz endpoint must verify the following before returning 200:

-   Consumer connection is active and consuming (Event Hub for bridge workers, Kafka for all others)

-   Producer connection is active (Kafka for all workers that emit; Event Hub consumer for bridge workers)

-   Source configuration is loaded and valid

-   Custom transform modules (if applicable) are loaded without errors

# 6. Error Handling and Dead-Letter Strategy

## 6.1 Retry Policy

Transient failures (Kafka send timeouts, Event Hub read timeouts, momentary connectivity issues, S3 download timeouts) should be retried with exponential backoff. The retry policy should be configurable per source with sensible defaults:

-   Max retries: 3 (default)

-   Initial backoff: 1 second

-   Max backoff: 30 seconds

-   Backoff multiplier: 2x

Every retry attempt must emit a WARN-level log event with the retry count and error details.

## 6.2 Dead-Letter Hub

Messages that exhaust their retry budget, or that fail non-retryable validation (schema violations, missing required fields), are sent to a shared Dead-Letter Kafka topic. The dead-lettered message must include:

-   The original message payload (unmodified)

-   The correlation_id and source_id

-   The failure reason and stage where failure occurred

-   A timestamp and the worker_id that dead-lettered it

Dead-letter messages must never be silently dropped. Every dead-letter event produces an ERROR-level log to the Logging Kafka topic.

## 6.3 Poison Message Protection

If a single message causes repeated failures in a transform worker, dead-letter it rather than letting it block the queue. Keep the detection logic simple—a consecutive failure counter is sufficient.

## 6.4 Backpressure: Alert and Pause

If a target Kafka topic (or an S3 destination for attachments) is slow, unavailable, or rejecting writes, the pipeline adopts an alert-and-pause strategy:

-   The affected worker detects consecutive failures exceeding the retry budget

-   An ERROR-level log event is emitted identifying the target, source, and failure reason

-   The worker pauses consumption (stops reading new messages)

-   The worker's /readyz endpoint returns non-200, signaling K8s to remove it from service

-   The worker periodically re-checks the target. When connectivity is restored, it resumes consumption and marks itself ready

This prevents message loss during outages. Messages remain unconsumed on the source Kafka topic (preserved by Kafka retention) or source Event Hub until the downstream target recovers. No local queuing or buffering is required.

# 7. Schema Validation

## 7.1 Validation Point

Schema validation occurs at the bridge layer, immediately after a raw event is consumed from the source Event Hub and before it is produced to an internal Kafka topic. This ensures that only structurally valid messages enter the pipeline.

## 7.2 Schema Definitions

Each source system's expected input schema is defined as part of its entry in config.yaml, referencing a JSON Schema file stored in the monorepo alongside the config. No external schema registry is needed at this scale.

## 7.3 Validation Behavior

-   Messages that pass validation are stamped with the schema version and produced to the internal Kafka topic

-   Messages that fail validation are immediately dead-lettered with the validation error details

-   Validation failures produce a validation_failed log event with the specific schema violation in the detail field

-   Schema validation must not be bypassable in production deployments

# 8. Side-Effect Rules Engine

The pipeline needs the flexibility to trigger external actions based on what it sees in the data. Rather than embedding this logic into transform code, the pipeline provides a lightweight rules engine. When a rule matches, the pipeline produces a message to a dedicated side-effect Kafka topic. That's it—the pipeline just moves data. Companion apps consume from the side-effect topics and do the heavy lifting (outbound API calls, notifications, etc.).

## 8.1 Rules Configuration

Rules are defined in a separate rules_config.yaml file in the monorepo. This is intentionally separate from config.yaml to keep source system configuration (how to ingest and transform) cleanly separated from side-effect behavior (what to do when something interesting happens).

**Each rule entry must define:**

-   Rule name (unique, human-readable identifier)

-   Source system it applies to (or all sources)

-   Pipeline stage to evaluate at (e.g., post-ingestion, post-validation, post-attachment, post-transform)

-   Condition: the matching logic to evaluate against the message state at that stage

-   Target Kafka topic: the dedicated side-effect topic to produce to when the rule fires

## 8.2 Stage Targeting

A rule can target any pipeline stage. This matters because the message looks different at each point in its lifecycle. For example:

-   A rule targeting post-ingestion sees the raw, validated event as it arrived from the source

-   A rule targeting post-attachment sees the message after an S3 document has been downloaded and parsed (e.g., parsed XML content from an Xactanalysis attachment is now available to inspect)

-   A rule targeting post-transform sees the fully enriched message

Each pipeline stage, after completing its primary work, evaluates all applicable rules from rules_config.yaml for the current source and stage. Rules that match produce a side-effect message.

## 8.3 Side-Effect Messages

When a rule fires, the pipeline produces a message to that rule's designated Kafka topic. The side-effect message carries the data that triggered the rule—meaning the state of the message at the stage where the rule evaluated. It should also include the correlation_id, source_id, rule name, and the stage that triggered it, so companion apps have full context.

Each distinct side effect gets its own dedicated Kafka topic. This keeps routing clean: a companion app subscribes to exactly one topic and gets exactly the events it cares about. No filtering on the consumer side.

## 8.4 Rule Complexity

Keep rules simple. The rules engine should support basic field-level conditions: equality checks, presence checks, and simple pattern matching. If a side-effect trigger requires complex logic (multi-step evaluation, lookups, aggregation), that logic belongs in a custom transform module that produces a flag field—and the rule simply checks for that flag.

The rules engine is not a general-purpose CEP (complex event processing) system. It's a lightweight conditional router. If it starts getting complicated, that's a signal to push complexity into the transform layer.

## 8.5 Logging

Every rule match produces a rule_matched log event to the Logging Kafka topic. The detail field includes the rule name, the stage where it fired, and the target side-effect topic. This ensures operators can trace not just what happened to a message, but what side effects it triggered.

Side-effect emit failures follow the same retry and dead-letter behavior as any other Kafka emit. A failed side-effect emit does not block or fail the main pipeline processing—the enriched message still proceeds to the target topic. The failure is logged and the side-effect message is dead-lettered independently.

# 9. Attachment Handling

Some source systems include pre-signed S3 URLs in their event payloads, referencing attachments (documents, images, PDFs) that are part of the claim record. The pipeline must download these files and upload them to a configured storage location as part of the enrichment phase.

## 9.1 When Attachments Apply

Not every source system produces attachments. Attachment handling is triggered when a message contains a field designated in the source's config.yaml entry as an attachment URL. If no attachment field is configured for a source, this phase is skipped entirely.

## 9.2 Processing Flow

-   The transform worker identifies the attachment URL field in the message (configured per source)

-   The file is downloaded from the pre-signed S3 URL to a temporary local path on the worker

-   The file is uploaded to the destination configured for that source (bucket path and credentials defined in config.yaml)

-   The enriched message is updated: the new storage location is added alongside the original URL (original URL is preserved, not replaced)

-   Temporary local file is deleted after successful upload

Both the download and upload are subject to the standard retry policy. If the attachment cannot be fetched or stored after retries, the entire message is dead-lettered.

## 9.3 Logging

Attachment operations produce two additional log events in the message's trace:

-   **attachment_downloaded:** Logged after successful download. Detail includes file size, content type, and download duration.

-   **attachment_uploaded:** Logged after successful upload. Detail includes destination path and upload duration.

Failed downloads or uploads produce WARN-level events on each retry and an ERROR-level event if dead-lettered.

## 9.4 Size and Performance

Attachments are expected to be in the 10--100 MB range. Workers handling attachment-heavy sources should be provisioned with sufficient memory and disk for temporary file storage. Attachment processing is inherently slower than pure message enrichment, so these workers may need different scaling characteristics than lightweight transform workers.

Keep the implementation simple: download to disk, upload from disk, delete. No streaming through memory, no parallel chunk transfers. Optimize only if profiling shows it's necessary.

# 10. Message Envelope Contract

Every message moving through the pipeline—from internal Kafka topics through to target output topics—must conform to a standard envelope. This envelope is the contract between the pipeline and downstream consumers.

  ——————-- —————- —————————————————————————--
  **Field**            **Type**         **Description**

  correlation_id       string (UUID)    Pipeline-assigned unique message ID

  source_event_id      string \| null   Original event ID from the upstream source system, if present

  source_id            string           Source system identifier (e.g., xactanalysis, claimx)

  schema_version       string           Version of the input schema the message was validated against

  ingested_at          ISO 8601         UTC timestamp when the pipeline first received the event

  processed_at         ISO 8601         UTC timestamp when enrichment completed

  transforms_applied   array            Ordered list of transform names and versions applied

  attachments          array \| null    List of attachment objects with original_url and stored_path, if applicable

  payload              object           The enriched message body
  ——————-- —————- —————————————————————————--

This envelope ensures that downstream Spark jobs or other consumers can inspect message lineage and locate attachments without querying the logging topic.

# 11. Phased Implementation Plan

The implementation is structured into four phases. Each phase produces a deployable increment that can be validated before proceeding. In keeping with the simplicity principle: do not build Phase 2 abstractions during Phase 1. Solve the problem in front of you with the simplest approach that works, and refactor only when the next phase demands it.

Phase 1: Foundation

**Goal:** Establish the core plumbing—a single source system, end-to-end streaming path with logging and health.

-   Set up monorepo structure with shared framework code

-   Implement base worker framework with health endpoints (/healthz, /readyz)

-   Build bridge worker (Event Hub consumer) that consumes from a source Event Hub, assigns correlation IDs, and produces to an internal Kafka topic

-   Build a passthrough transform worker (reads from internal Kafka topic, writes unmodified to target Kafka topic)

-   Implement structured logging to dedicated Logging Kafka topic with all base fields

-   Define and implement the message envelope contract

-   Validate end-to-end: a message enters via source Event Hub, is bridged to Kafka, and appears on the target Kafka topic with full correlation trace in the logging topic

**Exit criteria:** One source system's messages flow from source Event Hub through Kafka to target topic with complete, queryable log trace.

Phase 2: Transform Engine, Attachments, and Rules

**Goal:** Enable source-specific data enrichment, attachment handling, side-effect rules, and error management.

-   Implement source-specific transform logic (start with parameterized config)

-   Build attachment handling: download from pre-signed S3 URLs, upload to configured destination

-   Implement side-effect rules engine: rules_config.yaml parsing, per-stage evaluation, emit to dedicated side-effect Kafka topics

-   Add schema validation at ingestion with JSON Schema

-   Build dead-letter topic flow with full error context

-   Implement retry policy with exponential backoff

-   Add poison message detection

**Exit criteria:** A source's messages are validated, bridged to Kafka, transformed, attachments handled, side-effect rules firing correctly, and failures are dead-lettered with full diagnostics.

Phase 3: Multi-Source

**Goal:** Scale from one source system to many with separated compute and configuration.

-   Implement config.yaml-driven source definitions

-   Build pull-based ingestion workers (polling, CDC)

-   Deploy per-source worker instances from config

-   Verify that one source's failure does not block another's processing

-   Document the source onboarding runbook

**Exit criteria:** Multiple source systems running simultaneously with a documented, repeatable onboarding process.

Phase 4: Hardening

**Goal:** Production readiness—operational polish, resilience, and documentation.

-   Load testing at expected source count and message volume

-   Test failure scenarios: Event Hub outages, Kafka broker outages, worker crashes, poison messages, S3 unavailability, side-effect topic failures

-   Finalize operator documentation: runbooks for common failure modes, onboarding, and scaling

-   Establish alerting rules based on Logging Kafka topic error events

-   Performance baseline: document expected latency and throughput per phase

**Exit criteria:** System handles sustained load for all sources, recovers gracefully from failures, and operators can diagnose issues using logs and runbooks without developer intervention.

# 12. Schema Evolution

Source systems will change their event schemas over time. This section defines the compatibility policy, ownership model, and process for handling schema changes. These decisions directly affect the validation layer (Section 7) and the downstream consumer contract (Section 10).

## 12.1 Compatibility Policy

The default expectation is additive-only (backward-compatible) schema changes. JSON Schema's default behavior permits unknown properties, so new fields added by a source system pass validation without requiring a schema update on the pipeline side. This keeps the common case—a source adding a new field—zero-effort for the pipeline team.

The following changes are considered additive (non-breaking):

-   Adding new optional fields

-   Widening a field's type constraints (e.g., increasing a max length)

-   Adding new enum values to an existing field

The following changes are breaking and require the process defined in Section 12.3:

-   Removing or renaming an existing field

-   Changing a field's data type

-   Tightening constraints on a required field (e.g., reducing allowed enum values)

-   Changing the structure or nesting of existing fields

## 12.2 Schema Ownership

The pipeline team owns all schema files in the monorepo. Source system teams do not commit directly to the pipeline repo. However, a notification contract is required: source system teams must notify the pipeline team before deploying any schema change—additive or breaking—so the pipeline team can assess impact and update schemas, transforms, or downstream consumer documentation as needed.

This notification requirement must be documented in the source onboarding runbook (referenced in Section 3.3) and reinforced during onboarding. A schema change deployed without notification that causes validation failures is the source team's responsibility to remediate.

## 12.3 Breaking Change Process

When a source system must introduce a breaking schema change, the pipeline supports a temporary dual-schema validation window. During this window, a message is considered valid if it passes either the current schema or the incoming schema. This prevents message loss during the source team's rollout.

**Process:**

-   Source team notifies pipeline team of the upcoming breaking change and provides the new schema

-   Pipeline team adds the new schema to the monorepo and updates the source's config.yaml entry to reference both schemas (schema_refs accepts an array)

-   Pipeline deploys with dual-schema validation. Messages matching either schema pass validation

-   Source team rolls out their change. Both old-format and new-format messages are accepted during this period

-   Source team confirms migration is complete. Pipeline team removes the old schema and deploys, returning to single-schema validation

The dual-schema window should have a documented maximum duration agreed upon during planning (recommended default: 14 days). If the source team has not completed migration within this window, the pipeline team escalates. There is no support for indefinite multi-version schema validation—the goal is always to converge back to a single active schema per source.

## 12.4 Deployment Model

Schema changes require a full deploy cycle through the standard CI/CD pipeline. There is no hot-reload mechanism for schemas. This is a deliberate choice: at the expected scale (under 50 sources with infrequent schema changes), the operational simplicity and auditability of deploy-time schema loading outweighs the convenience of hot-reload. Every schema change is a git commit with a review trail, deployed through the same process as any other config or code change.

## 12.5 config.yaml Schema Fields

To support the dual-schema window, each source entry in config.yaml uses a schema_refs field that accepts either a single schema reference (the common case) or an array of references (the temporary breaking-change case). The validation layer evaluates schemas in order and accepts the message if any schema passes. This is the only change to the config.yaml contract described in Section 3.3.

**Example (single schema, normal operation):**

-   schema_refs: schemas/xactanalysis/v2.json

**Example (dual schema, during breaking change window):**

-   schema_refs: [schemas/xactanalysis/v2.json, schemas/xactanalysis/v3.json]