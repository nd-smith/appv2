"""End-to-end integration test: Bridge (mocked EH) → Kafka → Transform → Kafka."""

import threading

import pytest

from pipeline.envelope import MessageEnvelope
from pipeline.kafka_producer import KafkaProducer
from pipeline.workers.transform import TransformWorker

from .conftest import consume_messages

pytestmark = pytest.mark.integration


class TestEndToEnd:
    def test_full_pipeline_flow(
        self, kafka_bootstrap, create_topics, kafka_consumer_factory, tmp_path
    ):
        """Message flows: bridge produces to internal → transform → target.
        Logging topic has complete trace.
        """
        internal_topic = "test.e2e.internal"
        target_topic = "test.e2e.target"
        logging_topic = "test.e2e.logs"
        create_topics([internal_topic, target_topic, logging_topic])

        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
pipeline:
  kafka:
    bootstrap_servers: "{kafka_bootstrap}"
    logging_topic: "{logging_topic}"
    dead_letter_topic: "test.e2e.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "mock"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "{internal_topic}"
      target_topic: "{target_topic}"
      consumer_group: "test-e2e-transform"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
""")

        # Step 1: Simulate bridge worker output
        # (In real deployment, bridge consumes from Event Hub — here we produce directly)
        producer = KafkaProducer(kafka_bootstrap)

        event_data = {
            "eventType": "new_claim",
            "projectId": "P001",
        }
        envelope = MessageEnvelope.create(
            source_event_id="evt-100",
            source_id="claimx",
            payload=event_data,
        )
        correlation_id = envelope.correlation_id

        # Simulate bridge log events
        from pipeline.logging import KafkaLogSink, LogEvent

        log_sink = KafkaLogSink(producer=producer, topic=logging_topic)

        bridge_received = LogEvent.create(
            correlation_id=correlation_id,
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="message_received",
            level="INFO",
            detail="Received event evt-100",
            worker_id="bridge-pod-1",
        )
        log_sink.send(bridge_received)

        producer.produce(
            topic=internal_topic,
            value=envelope.to_json(),
            key=correlation_id,
        )

        bridge_emitted = LogEvent.create(
            correlation_id=correlation_id,
            source_id="claimx",
            worker_type="bridge",
            stage="bridge",
            event_type="emit_success",
            level="INFO",
            detail=f"Produced to {internal_topic}",
            worker_id="bridge-pod-1",
        )
        log_sink.send(bridge_emitted)
        producer.flush()

        # Step 2: Run transform worker
        worker = TransformWorker(
            source_id="claimx",
            config_path=str(config_file),
            health_port=0,
        )
        worker._health_server._port = 0

        t = threading.Thread(target=worker.run, daemon=True)
        t.start()

        # Step 3: Verify target topic has the enriched message
        target_consumer = kafka_consumer_factory(target_topic, "test-e2e-target-consumer")
        target_messages = consume_messages(target_consumer, count=1, timeout=15)

        # Stop the worker
        worker._running = False
        t.join(timeout=5)

        # Verify target message
        assert len(target_messages) == 1
        output = target_messages[0]
        assert output["correlation_id"] == correlation_id
        assert output["source_id"] == "claimx"
        assert output["source_event_id"] == "evt-100"
        assert output["payload"] == event_data
        assert "passthrough" in output["transforms_applied"]
        assert output["processed_at"] != ""

        # Step 4: Verify logging topic has trace events
        log_consumer = kafka_consumer_factory(logging_topic, "test-e2e-log-consumer")
        log_messages = consume_messages(log_consumer, count=4, timeout=15)

        # Should have at least: bridge received, bridge emit, transform received, transform emit
        event_types = [m.get("event_type") for m in log_messages]
        assert "message_received" in event_types
        assert "emit_success" in event_types

        # All log events for this correlation_id should have required fields
        for log_msg in log_messages:
            if log_msg.get("correlation_id") == correlation_id:
                for field in [
                    "correlation_id", "source_id", "timestamp",
                    "worker_type", "worker_id", "stage",
                    "event_type", "level", "detail",
                ]:
                    assert field in log_msg, f"Log event missing field: {field}"
