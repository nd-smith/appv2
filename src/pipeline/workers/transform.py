"""Passthrough transform worker: Kafka → Kafka.

Consumes from internal Kafka topic, updates processed_at and transforms_applied,
and produces to the target Kafka topic. Phase 1 is passthrough only.
"""

import structlog

from pipeline.envelope import MessageEnvelope
from pipeline.kafka_consumer import KafkaConsumer
from pipeline.kafka_producer import KafkaProducer
from pipeline.workers.base import BaseWorker

logger = structlog.get_logger()


class TransformWorker(BaseWorker):
    """Transform worker consuming from internal topic and producing to target topic."""

    def __init__(self, source_id: str, config_path: str = "config.yaml", health_port: int = 8080,
                 status_interval: int | None = None):
        super().__init__(
            source_id=source_id,
            worker_type="transform",
            config_path=config_path,
            health_port=health_port,
            status_interval=status_interval,
        )
        self._producer: KafkaProducer | None = None
        self._consumer: KafkaConsumer | None = None
        self._kafka_ready = False

    def setup(self) -> None:
        """Initialize Kafka producer and consumer."""
        self._producer = KafkaProducer(self.config.kafka.bootstrap_servers)
        self.log_sink.set_producer(self._producer)

        self._consumer = KafkaConsumer(
            bootstrap_servers=self.config.kafka.bootstrap_servers,
            group_id=self.source_config.kafka.consumer_group,
            topics=[self.source_config.kafka.internal_topic],
        )
        self._consumer.subscribe()
        self._kafka_ready = True

        self.health_registry.register("kafka", lambda: (self._kafka_ready, "connected"))

        self._logger.info("transform_setup_complete", source_id=self._source_id)
        self._emit_log("transform", "setup_complete", "INFO", "Transform worker setup complete")

    def process(self) -> None:
        """Poll for a message, apply passthrough transform, produce to target."""
        msg = self._consumer.poll(timeout=1.0)
        if msg is None:
            return

        try:
            envelope = MessageEnvelope.from_dict(msg)
        except (KeyError, TypeError) as e:
            self._logger.error("envelope_parse_error", error=str(e))
            return

        self._emit_log(
            stage="transform",
            event_type="message_received",
            level="INFO",
            detail=f"Processing {envelope.source_event_id}",
            correlation_id=envelope.correlation_id,
        )

        # Phase 1: passthrough — just mark as processed
        envelope.mark_processed("passthrough")

        topic = self.source_config.kafka.target_topic
        try:
            self._producer.produce(
                topic=topic,
                value=envelope.to_json(),
                key=envelope.correlation_id,
            )
            self._record_message()
            self._emit_log(
                stage="transform",
                event_type="emit_success",
                level="INFO",
                detail=f"Produced to {topic}",
                correlation_id=envelope.correlation_id,
            )
        except Exception as e:
            self._record_error()
            self._emit_log(
                stage="transform",
                event_type="emit_failed",
                level="ERROR",
                detail=str(e),
                correlation_id=envelope.correlation_id,
            )
            raise

    def shutdown(self) -> None:
        """Flush producer and close consumer."""
        if self._producer:
            self._producer.flush()
        if self._consumer:
            self._consumer.close()
        self._logger.info("transform_shutdown_complete")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Transform Worker: Kafka → Kafka")
    parser.add_argument("--source", required=True, help="Source ID from config.yaml")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--health-port", type=int, default=8080, help="Health server port")
    parser.add_argument("--status-interval", type=int, default=None,
                        help="Status print interval in seconds (default: 60, or STATUS_INTERVAL_SECONDS env)")
    args = parser.parse_args()

    worker = TransformWorker(
        source_id=args.source,
        config_path=args.config,
        health_port=args.health_port,
        status_interval=args.status_interval,
    )
    worker.run()


if __name__ == "__main__":
    main()
