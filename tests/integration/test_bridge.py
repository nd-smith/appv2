"""Integration tests for the bridge worker."""


import pytest

from pipeline.envelope import MessageEnvelope
from pipeline.kafka_producer import KafkaProducer

from .conftest import consume_messages

pytestmark = pytest.mark.integration


class TestBridgeWorkerIntegration:
    """Test bridge worker with real Kafka (Redpanda) and mocked Event Hub."""

    def test_bridge_produces_to_internal_topic(
        self, kafka_bootstrap, create_topics, kafka_consumer_factory, tmp_path
    ):
        """Simulate bridge receiving an event and producing to Kafka."""
        internal_topic = "test.bridge.internal"
        logging_topic = "test.bridge.logs"
        create_topics([internal_topic, logging_topic])

        # Create a config file for the test
        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
pipeline:
  kafka:
    bootstrap_servers: "{kafka_bootstrap}"
    logging_topic: "{logging_topic}"
    dead_letter_topic: "test.bridge.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "mock"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "{internal_topic}"
      target_topic: "test.bridge.target"
      consumer_group: "transform-claimx"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
""")

        # Instead of running the full bridge (which needs Event Hub),
        # test the core logic: envelope creation + Kafka produce
        producer = KafkaProducer(kafka_bootstrap)

        # Simulate what bridge._on_event does
        event_data = {
            "eventType": "new_claim",
            "projectId": "P001",
        }
        envelope = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload=event_data,
        )
        producer.produce(
            topic=internal_topic,
            value=envelope.to_json(),
            key=envelope.correlation_id,
        )
        producer.flush()

        # Consume and verify
        consumer = kafka_consumer_factory(internal_topic, "test-bridge-consumer")
        messages = consume_messages(consumer, count=1, timeout=10)

        assert len(messages) == 1
        msg = messages[0]
        assert msg["source_id"] == "claimx"
        assert msg["source_event_id"] == "evt-1"
        assert msg["correlation_id"] != ""
        assert msg["payload"] == event_data
