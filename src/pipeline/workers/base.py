"""Base worker framework with lifecycle management, signal handling, and health server."""

import os
import signal
import sys
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import structlog
from dotenv import load_dotenv

from pipeline.config import PipelineConfig, SourceConfig, load_config
from pipeline.health import HealthCheckRegistry, HealthServer
from pipeline.logging import KafkaLogSink, LogEvent, configure_structlog
from pipeline.status import StatusPrinter, WorkerStats

logger = structlog.get_logger()


class BaseWorker(ABC):
    """Base class for all pipeline workers.

    Lifecycle: __init__ → run() → [setup → run_loop → shutdown]
    Signal handling: SIGTERM/SIGINT trigger graceful shutdown.
    Health server: starts before setup, registers readiness checks.
    """

    def __init__(self, source_id: str, worker_type: str, config_path: str = "config.yaml",
                 health_port: int = 8080, status_interval: int | None = None):
        load_dotenv()
        configure_structlog()
        self._config = load_config(config_path)
        self._source_config = self._config.sources[source_id]
        self._source_id = source_id
        self._worker_type = worker_type
        self._running = False

        self._health_registry = HealthCheckRegistry()
        self._health_server = HealthServer(port=health_port, registry=self._health_registry)
        self._log_sink = KafkaLogSink(topic=self._config.kafka.logging_topic)

        self._stats = WorkerStats()
        self._stats_lock = threading.Lock()
        interval = status_interval or int(os.environ.get("STATUS_INTERVAL_SECONDS", "60"))
        self._status_printer = StatusPrinter(
            stats_fn=self._get_status_snapshot,
            source_id=source_id,
            worker_type=worker_type,
            interval=interval,
        )

        self._logger = structlog.get_logger(
            source_id=source_id,
            worker_type=worker_type,
        )

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def source_config(self) -> SourceConfig:
        return self._source_config

    @property
    def health_registry(self) -> HealthCheckRegistry:
        return self._health_registry

    @property
    def log_sink(self) -> KafkaLogSink:
        return self._log_sink

    def _emit_log(self, stage: str, event_type: str, level: str, detail: str,
                  correlation_id: str = "") -> None:
        """Emit a structured log event to the Kafka logging topic."""
        log_event = LogEvent.create(
            correlation_id=correlation_id,
            source_id=self._source_id,
            worker_type=self._worker_type,
            stage=stage,
            event_type=event_type,
            level=level,
            detail=detail,
        )
        self._log_sink.send(log_event)

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown.

        Only works in the main thread — silently skips in worker threads (e.g., tests).
        """
        import threading

        if threading.current_thread() is not threading.main_thread():
            self._logger.debug("skipping_signal_setup", reason="not main thread")
            return

        def handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            self._logger.info("signal_received", signal=sig_name)
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    def _record_message(self) -> None:
        """Record a successfully processed message."""
        with self._stats_lock:
            self._stats.messages_processed += 1
            self._stats.last_message_at = datetime.now(timezone.utc)

    def _record_error(self) -> None:
        """Record a processing error."""
        with self._stats_lock:
            self._stats.errors += 1

    def _get_status_snapshot(self) -> dict:
        """Return a point-in-time copy of stats for the status printer."""
        with self._stats_lock:
            return {
                "started_at": self._stats.started_at,
                "messages_processed": self._stats.messages_processed,
                "errors": self._stats.errors,
                "last_message_at": self._stats.last_message_at,
            }

    def run(self) -> None:
        """Main entry point. Manages full lifecycle."""
        self._logger.info("worker_starting")
        self._setup_signals()
        self._health_server.start()
        self._logger.info("health_server_started")
        self._status_printer.start()

        try:
            self.setup()
            self._running = True
            self._logger.info("worker_running")
            self.run_loop()
        except Exception:
            self._logger.exception("worker_fatal_error")
            sys.exit(1)
        finally:
            self._logger.info("worker_shutting_down")
            self._status_printer.stop()
            self.shutdown()
            self._health_server.stop()
            self._logger.info("worker_stopped")

    def run_loop(self) -> None:
        """Default run loop — calls process() repeatedly while running."""
        while self._running:
            self.process()

    @abstractmethod
    def setup(self) -> None:
        """Initialize resources (consumers, producers). Called once before run_loop."""

    @abstractmethod
    def process(self) -> None:
        """Process one unit of work. Called repeatedly in run_loop."""

    def shutdown(self) -> None:
        """Clean up resources. Override to add custom cleanup."""
