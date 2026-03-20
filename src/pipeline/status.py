"""Periodic status printer for pipeline workers.

Runs in a daemon thread alongside the main worker event loop,
printing a plain-text status summary to stdout at a configurable interval.
"""

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass
class WorkerStats:
    """Simple counters for worker status reporting."""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages_processed: int = 0
    errors: int = 0
    last_message_at: datetime | None = None


class StatusPrinter:
    """Periodically prints a plain-text status summary to stdout.

    Pattern mirrors HealthServer: daemon thread, start/stop lifecycle.
    """

    def __init__(
        self,
        stats_fn: Callable[[], dict],
        source_id: str,
        worker_type: str,
        interval: int = 60,
    ):
        self._stats_fn = stats_fn
        self._source_id = source_id
        self._worker_type = worker_type
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the status printer in a daemon thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the printer thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Print status at intervals, sleeping in 1s chunks for prompt shutdown."""
        while not self._stop_event.is_set():
            elapsed = 0
            while elapsed < self._interval and not self._stop_event.is_set():
                self._stop_event.wait(timeout=1)
                elapsed += 1
            if not self._stop_event.is_set():
                stats = self._stats_fn()
                print(self._format_status(stats), flush=True)

    def _format_status(self, stats: dict) -> str:
        """Produce the plain-text status line."""
        worker_id = os.environ.get("HOSTNAME", os.environ.get("POD_NAME", "local"))
        header = f"{self._worker_type}/{self._source_id} @ {worker_id}"

        now = datetime.now(timezone.utc)
        started_at = stats["started_at"]
        uptime_secs = int((now - started_at).total_seconds())
        uptime_str = _format_duration(uptime_secs)

        messages = stats["messages_processed"]
        errors = stats["errors"]

        if uptime_secs > 0 and messages > 0:
            rate = messages / (uptime_secs / 60)
            rate_str = f"{rate:,.1f} msg/min"
        else:
            rate_str = "0 msg/min"

        last_message_at = stats["last_message_at"]
        if last_message_at is not None:
            last_ago = int((now - last_message_at).total_seconds())
            last_str = f"{_format_duration(last_ago)} ago"
        else:
            last_str = "no messages yet"

        detail = f"  messages: {messages:,} | errors: {errors:,} | rate: {rate_str} | last msg: {last_str}"
        width = max(len(f"--- STATUS [{header}] uptime={uptime_str} ---"), len(detail))
        sep = "-" * width

        return (
            f"--- STATUS [{header}] uptime={uptime_str} ---\n"
            f"{detail}\n"
            f"{sep}"
        )


def _format_duration(total_seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours}h {minutes}m {seconds}s"
