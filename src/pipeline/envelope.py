"""Message envelope contract for the pipeline.

Every message flowing through the pipeline is wrapped in this envelope.
The envelope carries metadata required for tracing, auditing, and processing.
"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class MessageEnvelope:
    correlation_id: str
    source_event_id: str
    source_id: str
    schema_version: str
    ingested_at: str
    processed_at: str
    transforms_applied: list[str]
    attachments: list[dict]
    payload: dict

    @classmethod
    def create(
        cls,
        source_event_id: str,
        source_id: str,
        payload: dict,
        schema_version: str = "1.0",
        attachments: list[dict] | None = None,
    ) -> "MessageEnvelope":
        """Factory method to create a new envelope at ingestion time."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            correlation_id=str(uuid.uuid4()),
            source_event_id=source_event_id,
            source_id=source_id,
            schema_version=schema_version,
            ingested_at=now,
            processed_at="",
            transforms_applied=[],
            attachments=attachments or [],
            payload=payload,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MessageEnvelope":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: str) -> "MessageEnvelope":
        return cls.from_dict(json.loads(raw))

    def mark_processed(self, transform_name: str) -> None:
        """Mark the envelope as processed by a transform stage."""
        self.processed_at = datetime.now(timezone.utc).isoformat()
        self.transforms_applied.append(transform_name)
