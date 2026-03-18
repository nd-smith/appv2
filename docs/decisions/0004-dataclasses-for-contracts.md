# 0004: stdlib dataclasses for Message Envelope and Log Event Models

**Date:** 2026-03-18
**Status:** Accepted

## Context
Need data models for the message envelope contract and structured log events. Options considered: dataclasses (stdlib), pydantic, attrs, plain dicts.

## Decision
Use Python stdlib `dataclasses` for all data contracts in Phase 1: message envelope, log event structure, and configuration objects.

## PRD Alignment
Follows the CLAUDE.md principle "Do not build Phase N+1 abstractions during Phase N." Dataclasses provide typed, documented structures without adding dependencies. The PRD's message envelope contract (correlation_id, source_event_id, etc.) maps directly to dataclass fields.

## Consequences
- **Easier:** Zero additional dependencies. Clear field definitions with types. Simple to_dict via `dataclasses.asdict()`. Familiar to any Python developer.
- **Harder:** No built-in validation (unlike pydantic). If Phase 2 schema validation requires runtime type checking on message fields, we may upgrade to pydantic then.
- **Trade-off:** We accept manual validation in factory methods for Phase 1. This keeps the dependency footprint minimal and avoids premature abstraction. Migration to pydantic later would be mechanical (change decorator, add validators).
