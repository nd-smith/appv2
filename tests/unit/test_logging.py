"""Unit tests for structured logging."""

import json
from unittest.mock import MagicMock

from pipeline.logging import KafkaLogSink, LogEvent, configure_structlog


class TestLogEvent:
    def test_create_sets_all_fields(self):
        event = LogEvent.create(
            correlation_id="abc-123",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="message_received",
            level="INFO",
            detail="test message",
            worker_id="test-pod",
        )
        assert event.correlation_id == "abc-123"
        assert event.source_id == "claimx"
        assert event.worker_type == "bridge"
        assert event.stage == "bridge"
        assert event.event_type == "message_received"
        assert event.level == "INFO"
        assert event.detail == "test message"
        assert event.worker_id == "test-pod"
        assert event.timestamp != ""

    def test_create_default_worker_id(self):
        event = LogEvent.create(
            correlation_id="abc-123",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="test",
            level="INFO",
            detail="test",
        )
        # Should fall back to hostname
        assert event.worker_id != ""

    def test_to_dict_contains_all_required_fields(self):
        event = LogEvent.create(
            correlation_id="abc-123",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="message_received",
            level="INFO",
            detail="test",
            worker_id="pod-1",
        )
        d = event.to_dict()
        required_fields = [
            "correlation_id", "source_id", "timestamp", "worker_type",
            "worker_id", "stage", "event_type", "level", "detail",
        ]
        for field in required_fields:
            assert field in d, f"Missing required field: {field}"


class TestKafkaLogSink:
    def test_send_with_producer(self):
        mock_producer = MagicMock()
        sink = KafkaLogSink(producer=mock_producer, topic="pipeline.logs")

        event = LogEvent.create(
            correlation_id="abc-123",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="test",
            level="INFO",
            detail="test detail",
            worker_id="pod-1",
        )
        sink.send(event)

        mock_producer.produce.assert_called_once()
        call_args = mock_producer.produce.call_args
        assert call_args[0][0] == "pipeline.logs"
        # Verify the produced message is valid JSON with all fields
        produced_json = json.loads(call_args[0][1])
        assert produced_json["correlation_id"] == "abc-123"

    def test_send_without_producer_falls_back_to_stderr(self, capsys):
        sink = KafkaLogSink(producer=None, topic="pipeline.logs")

        event = LogEvent.create(
            correlation_id="abc-123",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="test",
            level="INFO",
            detail="test detail",
            worker_id="pod-1",
        )
        sink.send(event)

        captured = capsys.readouterr()
        parsed = json.loads(captured.err)
        assert parsed["correlation_id"] == "abc-123"

    def test_set_producer(self):
        sink = KafkaLogSink(producer=None)
        mock_producer = MagicMock()
        sink.set_producer(mock_producer)

        event = LogEvent.create(
            correlation_id="x",
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="test",
            level="INFO",
            detail="test",
            worker_id="pod-1",
        )
        sink.send(event)
        mock_producer.produce.assert_called_once()


class TestConfigureStructlog:
    def test_configure_does_not_raise(self):
        configure_structlog()
