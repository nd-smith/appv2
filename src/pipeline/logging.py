"""Structured logging configuration using structlog.

All log events are JSON and sent to a Kafka logging topic.
Required fields per PRD: correlation_id, source_id, timestamp,
worker_type, worker_id, stage, event_type, level, detail.
"""

import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import structlog


@dataclass
class LogEvent:
    """Structured log event matching the PRD contract."""

    correlation_id: str
    source_id: str
    timestamp: str
    worker_type: str
    worker_id: str
    stage: str
    event_type: str
    level: str
    detail: str

    @classmethod
    def create(
        cls,
        correlation_id: str,
        source_id: str,
        worker_type: str,
        stage: str,
        event_type: str,
        level: str,
        detail: str,
        worker_id: str | None = None,
    ) -> "LogEvent":
        return cls(
            correlation_id=correlation_id,
            source_id=source_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            worker_type=worker_type,
            worker_id=worker_id or os.environ.get("HOSTNAME", socket.gethostname()),
            stage=stage,
            event_type=event_type,
            level=level,
            detail=detail,
        )

    def to_dict(self) -> dict:
        return asdict(self)


class KafkaLogSink:
    """Sends structured log events to a Kafka logging topic.

    Accepts a kafka_producer (pipeline.kafka_producer.KafkaProducer) and topic name.
    Falls back to stderr if no producer is configured (e.g., during startup).
    """

    def __init__(self, producer=None, topic: str = "pipeline.logs"):
        self._producer = producer
        self._topic = topic

    def set_producer(self, producer) -> None:
        self._producer = producer

    def send(self, log_event: LogEvent) -> None:
        import json

        data = log_event.to_dict()
        if self._producer:
            self._producer.produce(self._topic, json.dumps(data))
        else:
            import sys

            print(json.dumps(data), file=sys.stderr)


def configure_structlog() -> None:
    """Configure structlog for JSON output with context binding."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_binds) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with optional initial context bindings."""
    return structlog.get_logger(**initial_binds)
