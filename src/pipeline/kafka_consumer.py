"""Kafka consumer wrapper around confluent-kafka."""

import structlog
from confluent_kafka import Consumer, KafkaError

logger = structlog.get_logger()


class KafkaConsumer:
    """Wraps confluent-kafka Consumer with poll-based consumption and structured logging."""

    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str], **extra_config):
        config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
            **extra_config,
        }
        self._consumer = Consumer(config)
        self._topics = topics
        self._subscribed = False

    def subscribe(self) -> None:
        """Subscribe to configured topics."""
        self._consumer.subscribe(self._topics)
        self._subscribed = True
        logger.info("kafka_consumer_subscribed", topics=self._topics)

    def poll(self, timeout: float = 1.0) -> dict | None:
        """Poll for a message. Returns decoded message dict or None."""
        if not self._subscribed:
            self.subscribe()

        msg = self._consumer.poll(timeout)
        if msg is None:
            return None

        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                return None
            logger.error("kafka_consumer_error", error=str(msg.error()))
            return None

        import json

        try:
            value = json.loads(msg.value().decode("utf-8"))
            return value
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("kafka_message_decode_error", error=str(e))
            return None

    def close(self) -> None:
        """Close the consumer."""
        self._consumer.close()
        logger.info("kafka_consumer_closed")
