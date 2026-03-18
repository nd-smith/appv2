"""Bridge worker: Event Hub → Kafka.

Consumes events from Azure Event Hub, wraps them in a message envelope
(assigning correlation_id), and produces to the internal Kafka topic.
"""

import threading

import structlog

from pipeline.envelope import MessageEnvelope
from pipeline.eventhub_consumer import EventHubConsumer
from pipeline.kafka_producer import KafkaProducer
from pipeline.workers.base import BaseWorker

logger = structlog.get_logger()


class BridgeWorker(BaseWorker):
    """Bridge worker consuming from Event Hub and producing to Kafka."""

    def __init__(self, source_id: str, config_path: str = "config.yaml", health_port: int = 8080):
        super().__init__(
            source_id=source_id,
            worker_type="bridge",
            config_path=config_path,
            health_port=health_port,
        )
        self._producer: KafkaProducer | None = None
        self._eh_consumer: EventHubConsumer | None = None
        self._eh_thread: threading.Thread | None = None
        self._kafka_ready = False

    def setup(self) -> None:
        """Initialize Kafka producer and Event Hub consumer."""
        self._producer = KafkaProducer(self.config.kafka.bootstrap_servers)
        self.log_sink.set_producer(self._producer)
        self._kafka_ready = True

        self._eh_consumer = EventHubConsumer(
            connection_string=self.source_config.eventhub.connection_string,
            consumer_group=self.source_config.eventhub.consumer_group,
        )

        self.health_registry.register("kafka", lambda: (self._kafka_ready, "connected"))

        self._logger.info("bridge_setup_complete", source_id=self._source_id)
        self._emit_log("bridge", "setup_complete", "INFO", "Bridge worker setup complete")

    def _on_event(self, event_data: dict, event_id: str) -> None:
        """Handle an incoming Event Hub event."""
        envelope = MessageEnvelope.create(
            source_event_id=event_id,
            source_id=self._source_id,
            payload=event_data,
        )

        self._emit_log(
            stage="bridge",
            event_type="message_received",
            level="INFO",
            detail=f"Received event {event_id}",
            correlation_id=envelope.correlation_id,
        )

        topic = self.source_config.kafka.internal_topic
        try:
            self._producer.produce(
                topic=topic,
                value=envelope.to_json(),
                key=envelope.correlation_id,
            )
            self._emit_log(
                stage="bridge",
                event_type="emit_success",
                level="INFO",
                detail=f"Produced to {topic}",
                correlation_id=envelope.correlation_id,
            )
        except Exception as e:
            self._emit_log(
                stage="bridge",
                event_type="emit_failed",
                level="ERROR",
                detail=str(e),
                correlation_id=envelope.correlation_id,
            )
            raise

    def run_loop(self) -> None:
        """Start Event Hub consumer in a thread and block until shutdown signal."""
        self._eh_thread = threading.Thread(
            target=self._eh_consumer.start,
            args=(self._on_event,),
            daemon=True,
        )
        self._eh_thread.start()
        self._logger.info("eventhub_consumer_started")

        import time

        while self._running:
            time.sleep(0.5)

    def process(self) -> None:
        """Not used — bridge uses Event Hub's receive callback model."""

    def shutdown(self) -> None:
        """Flush Kafka producer and close Event Hub consumer."""
        if self._producer:
            self._producer.flush()
        if self._eh_consumer:
            self._eh_consumer.close()
        self._logger.info("bridge_shutdown_complete")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bridge Worker: Event Hub → Kafka")
    parser.add_argument("--source", required=True, help="Source ID from config.yaml")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--health-port", type=int, default=8080, help="Health server port")
    args = parser.parse_args()

    worker = BridgeWorker(
        source_id=args.source,
        config_path=args.config,
        health_port=args.health_port,
    )
    worker.run()


if __name__ == "__main__":
    main()
