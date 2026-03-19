"""Integration tests for the transform worker."""

import threading

import pytest

from pipeline.envelope import MessageEnvelope
from pipeline.kafka_producer import KafkaProducer
from pipeline.workers.transform import TransformWorker

from .conftest import consume_messages

pytestmark = pytest.mark.integration


class TestTransformWorkerIntegration:
    def test_transform_consumes_and_produces(
        self, kafka_bootstrap, create_topics, kafka_consumer_factory, tmp_path
    ):
        """Transform worker reads from internal topic, produces to target topic."""
        internal_topic = "test.transform.internal"
        target_topic = "test.transform.target"
        logging_topic = "test.transform.logs"
        create_topics([internal_topic, target_topic, logging_topic])

        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
pipeline:
  kafka:
    bootstrap_servers: "{kafka_bootstrap}"
    logging_topic: "{logging_topic}"
    dead_letter_topic: "test.transform.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "mock"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "{internal_topic}"
      target_topic: "{target_topic}"
      consumer_group: "test-transform-group"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
""")

        # Produce a message to the internal topic (simulating bridge output)
        producer = KafkaProducer(kafka_bootstrap)
        envelope = MessageEnvelope.create(
            source_event_id="evt-1",
            source_id="claimx",
            payload={"eventType": "new_claim"},
        )
        producer.produce(
            topic=internal_topic,
            value=envelope.to_json(),
            key=envelope.correlation_id,
        )
        producer.flush()

        # Run transform worker in a thread
        worker = TransformWorker(
            source_id="claimx",
            config_path=str(config_file),
            health_port=0,
        )
        # Override health server port to 0 (random)
        worker._health_server._port = 0

        def run_worker():
            worker.run()

        t = threading.Thread(target=run_worker, daemon=True)
        t.start()

        # Consume from the target topic
        consumer = kafka_consumer_factory(target_topic, "test-transform-output")
        messages = consume_messages(consumer, count=1, timeout=15)

        # Stop the worker
        worker._running = False
        t.join(timeout=5)

        assert len(messages) == 1
        msg = messages[0]
        assert msg["source_id"] == "claimx"
        assert msg["correlation_id"] == envelope.correlation_id
        assert "passthrough" in msg["transforms_applied"]
        assert msg["processed_at"] != ""
