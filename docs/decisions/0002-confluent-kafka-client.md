# 0002: confluent-kafka as Kafka Client Library

**Date:** 2026-03-18
**Status:** Accepted

## Context
Need a Python Kafka client for producing and consuming messages. Options considered: confluent-kafka (librdkafka-based), aiokafka (asyncio), kafka-python (pure Python).

## Decision
Use `confluent-kafka` as the sole Kafka client library.

## PRD Alignment
Aligns with the dual-transport architecture (Event Hub + Kafka). confluent-kafka is the production-grade standard for Python Kafka applications. The PRD requires reliable Kafka interaction for internal topics, target topics, logging, and dead-letter — confluent-kafka handles all of these.

## Consequences
- **Easier:** Battle-tested C library (librdkafka) handles connection management, batching, compression, and retries. Extensive configuration options. Strong community support.
- **Harder:** Requires librdkafka C library at build time (handled by pip wheel). Slightly more complex error handling via callbacks vs. simple exceptions.
- **Trade-off:** The callback-based delivery reporting model requires wrapping for clean structured logging, but this is straightforward and done once in the producer wrapper.
