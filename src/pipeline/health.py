"""Threaded HTTP health server for /healthz and /readyz endpoints.

Runs in a daemon thread alongside the main worker event loop.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthCheckRegistry:
    """Registry of readiness checks. All must pass for /readyz to return 200."""

    def __init__(self):
        self._checks: dict[str, callable] = {}
        self._lock = threading.Lock()

    def register(self, name: str, check: callable) -> None:
        """Register a readiness check. check() should return (bool, str)."""
        with self._lock:
            self._checks[name] = check

    def evaluate(self) -> tuple[bool, dict]:
        """Evaluate all checks. Returns (all_healthy, details)."""
        with self._lock:
            checks = dict(self._checks)

        results = {}
        all_healthy = True
        for name, check in checks.items():
            try:
                healthy, detail = check()
            except Exception as e:
                healthy, detail = False, str(e)
            results[name] = {"healthy": healthy, "detail": detail}
            if not healthy:
                all_healthy = False

        return all_healthy, results


class _HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health endpoints."""

    registry: HealthCheckRegistry = None

    def do_GET(self):
        if self.path == "/healthz":
            self._respond(200, {"status": "ok"})
        elif self.path == "/readyz":
            healthy, details = self.registry.evaluate()
            status = 200 if healthy else 503
            body = {
                "status": "ready" if healthy else "not_ready",
                "checks": details,
            }
            self._respond(status, body)
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging


class HealthServer:
    """HTTP health server that runs in a daemon thread."""

    def __init__(self, port: int = 8080, registry: HealthCheckRegistry | None = None):
        self._port = port
        self._registry = registry or HealthCheckRegistry()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def registry(self) -> HealthCheckRegistry:
        return self._registry

    def start(self) -> None:
        """Start the health server in a daemon thread."""
        handler_class = type(
            "_BoundHealthHandler",
            (_HealthHandler,),
            {"registry": self._registry},
        )
        self._server = HTTPServer(("0.0.0.0", self._port), handler_class)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the health server."""
        if self._server:
            self._server.shutdown()
