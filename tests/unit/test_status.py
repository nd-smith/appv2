"""Unit tests for the status printer."""

import time
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from pipeline.status import StatusPrinter, WorkerStats, _format_duration


class TestWorkerStats:
    def test_initial_values(self):
        stats = WorkerStats()
        assert stats.messages_processed == 0
        assert stats.errors == 0
        assert stats.last_message_at is None
        assert isinstance(stats.started_at, datetime)

    def test_increment_messages(self):
        stats = WorkerStats()
        stats.messages_processed += 1
        stats.messages_processed += 1
        assert stats.messages_processed == 2

    def test_increment_errors(self):
        stats = WorkerStats()
        stats.errors += 1
        assert stats.errors == 1

    def test_last_message_at_updated(self):
        stats = WorkerStats()
        now = datetime.now(timezone.utc)
        stats.last_message_at = now
        assert stats.last_message_at == now


class TestFormatDuration:
    def test_seconds_only(self):
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3723) == "1h 2m 3s"

    def test_zero(self):
        assert _format_duration(0) == "0s"


class TestStatusPrinter:
    def _make_stats_fn(self, messages=0, errors=0, last_message_at=None):
        started = datetime.now(timezone.utc)
        return lambda: {
            "started_at": started,
            "messages_processed": messages,
            "errors": errors,
            "last_message_at": last_message_at,
        }

    def test_prints_to_stdout(self):
        """StatusPrinter should print at least once with a short interval."""
        stats_fn = self._make_stats_fn(messages=42, errors=1)
        printer = StatusPrinter(
            stats_fn=stats_fn,
            source_id="claimx",
            worker_type="bridge",
            interval=1,
        )

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            printer.start()
            time.sleep(2.5)
            printer.stop()
            output = mock_stdout.getvalue()

        assert "STATUS" in output
        assert "bridge/claimx" in output
        assert "42" in output

    def test_stop_halts_printing(self):
        """After stop(), no more output should appear."""
        stats_fn = self._make_stats_fn()
        printer = StatusPrinter(
            stats_fn=stats_fn,
            source_id="test",
            worker_type="bridge",
            interval=1,
        )

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            printer.start()
            time.sleep(2.5)
            printer.stop()
            output_at_stop = mock_stdout.getvalue()
            time.sleep(2)
            output_after = mock_stdout.getvalue()

        assert output_at_stop == output_after

    def test_format_contains_key_info(self):
        """The formatted status should contain messages, errors, uptime."""
        stats_fn = self._make_stats_fn(messages=100, errors=5)
        printer = StatusPrinter(
            stats_fn=stats_fn,
            source_id="validate",
            worker_type="transform",
            interval=60,
        )
        stats = stats_fn()
        output = printer._format_status(stats)

        assert "STATUS" in output
        assert "transform/validate" in output
        assert "100" in output
        assert "5" in output
        assert "uptime=" in output

    def test_zero_messages_shows_no_messages_yet(self):
        """When no messages processed, should show 'no messages yet'."""
        stats_fn = self._make_stats_fn(messages=0)
        printer = StatusPrinter(
            stats_fn=stats_fn,
            source_id="test",
            worker_type="bridge",
            interval=60,
        )
        stats = stats_fn()
        output = printer._format_status(stats)

        assert "no messages yet" in output

    def test_format_with_last_message(self):
        """When last_message_at is set, should show time ago."""
        now = datetime.now(timezone.utc)
        stats_fn = self._make_stats_fn(messages=10, last_message_at=now)
        printer = StatusPrinter(
            stats_fn=stats_fn,
            source_id="test",
            worker_type="bridge",
            interval=60,
        )
        stats = stats_fn()
        output = printer._format_status(stats)

        assert "ago" in output
        assert "no messages yet" not in output
