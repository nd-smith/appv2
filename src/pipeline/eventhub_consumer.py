"""Event Hub consumer wrapper around azure-eventhub SDK."""

import structlog
from azure.eventhub import EventHubConsumerClient

logger = structlog.get_logger()


class EventHubConsumer:
    """Wraps azure-eventhub EventHubConsumerClient for consuming events."""

    def __init__(self, connection_string: str, consumer_group: str):
        self._connection_string = connection_string
        self._consumer_group = consumer_group
        self._client: EventHubConsumerClient | None = None
        self._on_event_callback = None

    def start(self, on_event) -> None:
        """Start receiving events. on_event(event_data: dict, event_id: str) is called per event."""
        self._on_event_callback = on_event
        self._client = EventHubConsumerClient.from_connection_string(
            conn_str=self._connection_string,
            consumer_group=self._consumer_group,
        )
        logger.info(
            "eventhub_consumer_started",
            consumer_group=self._consumer_group,
        )
        self._client.receive(
            on_event=self._handle_event,
            starting_position="-1",
        )

    def _handle_event(self, partition_context, event):
        """Internal handler that extracts data and calls the user callback."""
        if event is None:
            return

        try:
            event_data = event.body_as_json()
        except Exception:
            event_data = {"raw": event.body_as_str()}

        event_id = event.properties.get(b"x-opt-sequence-number", b"unknown")
        if isinstance(event_id, bytes):
            event_id = event_id.decode("utf-8", errors="replace")
        if event.sequence_number is not None:
            event_id = str(event.sequence_number)
        else:
            event_id = str(event_id)

        if self._on_event_callback:
            self._on_event_callback(event_data, event_id)

        partition_context.update_checkpoint(event)

    def close(self) -> None:
        """Close the Event Hub consumer."""
        if self._client:
            self._client.close()
            logger.info("eventhub_consumer_closed")
