"""Kafka producer wrapper around confluent-kafka."""


import structlog
from confluent_kafka import Producer

logger = structlog.get_logger()


class KafkaProducer:
    """Wraps confluent-kafka Producer with structured logging and delivery callbacks."""

    def __init__(self, bootstrap_servers: str, **extra_config):
        config = {
            "bootstrap.servers": bootstrap_servers,
            "linger.ms": 5,
            "batch.num.messages": 100,
            **extra_config,
        }
        self._producer = Producer(config)
        self._bootstrap_servers = bootstrap_servers

    def _delivery_callback(self, err, msg):
        if err:
            logger.error(
                "kafka_delivery_failed",
                topic=msg.topic(),
                error=str(err),
            )
        else:
            logger.debug(
                "kafka_delivery_success",
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
            )

    def produce(self, topic: str, value: str, key: str | None = None, headers: dict | None = None):
        """Produce a message to a Kafka topic."""
        kafka_headers = [(k, v.encode()) for k, v in headers.items()] if headers else None
        self._producer.produce(
            topic=topic,
            value=value.encode("utf-8"),
            key=key.encode("utf-8") if key else None,
            headers=kafka_headers,
            callback=self._delivery_callback,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        """Flush pending messages. Returns number of messages still in queue."""
        return self._producer.flush(timeout)
