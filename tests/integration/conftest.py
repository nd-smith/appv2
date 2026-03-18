"""Integration test fixtures — requires Redpanda running via docker-compose."""

import json
import os
import time

import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")


def kafka_available() -> bool:
    """Check if Kafka/Redpanda is reachable."""
    try:
        admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP})
        admin.list_topics(timeout=5)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def kafka_bootstrap():
    if not kafka_available():
        pytest.skip("Kafka/Redpanda not available — run docker compose up -d")
    return KAFKA_BOOTSTRAP


@pytest.fixture
def create_topics(kafka_bootstrap):
    """Factory fixture to create Kafka topics for a test."""
    admin = AdminClient({"bootstrap.servers": kafka_bootstrap})
    created = []

    def _create(topic_names: list[str]):
        new_topics = [
            NewTopic(name, num_partitions=1, replication_factor=1)
            for name in topic_names
        ]
        futures = admin.create_topics(new_topics)
        for topic, future in futures.items():
            try:
                future.result(timeout=10)
            except Exception:
                pass  # Topic may already exist
            created.append(topic)
        # Brief wait for topic metadata propagation
        time.sleep(0.5)
        return topic_names

    yield _create

    # Cleanup: delete created topics
    if created:
        futures = admin.delete_topics(created)
        for topic, future in futures.items():
            try:
                future.result(timeout=10)
            except Exception:
                pass


@pytest.fixture
def kafka_producer(kafka_bootstrap):
    """Raw confluent-kafka producer for test setup."""
    p = Producer({"bootstrap.servers": kafka_bootstrap})
    yield p
    p.flush(10)


@pytest.fixture
def kafka_consumer_factory(kafka_bootstrap):
    """Factory to create test consumers."""
    consumers = []

    def _create(topic: str, group_id: str = "test-group"):
        c = Consumer({
            "bootstrap.servers": kafka_bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
        })
        c.subscribe([topic])
        consumers.append(c)
        return c

    yield _create

    for c in consumers:
        c.close()


def consume_messages(consumer, count: int = 1, timeout: float = 15.0) -> list[dict]:
    """Helper to consume N messages with timeout."""
    messages = []
    deadline = time.time() + timeout
    while len(messages) < count and time.time() < deadline:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        try:
            messages.append(json.loads(msg.value().decode("utf-8")))
        except Exception:
            pass
    return messages
