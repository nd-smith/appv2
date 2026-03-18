"""Unit tests for the message envelope contract."""

import json
import uuid

from pipeline.envelope import MessageEnvelope


class TestMessageEnvelopeCreate:
    def test_create_assigns_uuid_correlation_id(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={"claim_id": "C001"},
        )
        # Should be a valid UUID v4
        parsed = uuid.UUID(env.correlation_id)
        assert parsed.version == 4

    def test_create_sets_source_fields(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={"claim_id": "C001"},
        )
        assert env.source_event_id == "evt-1"
        assert env.source_id == "claimx"
        assert env.payload == {"claim_id": "C001"}

    def test_create_sets_defaults(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
        )
        assert env.schema_version == "1.0"
        assert env.ingested_at != ""
        assert env.processed_at == ""
        assert env.transforms_applied == []
        assert env.attachments == []

    def test_create_with_custom_schema_version(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
            schema_version="2.0",
        )
        assert env.schema_version == "2.0"

    def test_create_with_attachments(self):
        attachments = [{"url": "https://example.com/file.pdf"}]
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
            attachments=attachments,
        )
        assert env.attachments == attachments


class TestMessageEnvelopeSerialization:
    def test_to_dict_roundtrip(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={"key": "value"},
        )
        d = env.to_dict()
        restored = MessageEnvelope.from_dict(d)
        assert restored.correlation_id == env.correlation_id
        assert restored.payload == env.payload

    def test_to_json_roundtrip(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={"key": "value"},
        )
        j = env.to_json()
        restored = MessageEnvelope.from_json(j)
        assert restored.correlation_id == env.correlation_id
        assert restored.payload == env.payload

    def test_to_json_is_valid_json(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
        )
        parsed = json.loads(env.to_json())
        assert "correlation_id" in parsed
        assert "source_event_id" in parsed


class TestMessageEnvelopeMarkProcessed:
    def test_mark_processed_updates_fields(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
        )
        assert env.processed_at == ""
        assert env.transforms_applied == []

        env.mark_processed("passthrough")

        assert env.processed_at != ""
        assert env.transforms_applied == ["passthrough"]

    def test_mark_processed_multiple_times(self):
        env = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={},
        )
        env.mark_processed("step1")
        env.mark_processed("step2")

        assert env.transforms_applied == ["step1", "step2"]
