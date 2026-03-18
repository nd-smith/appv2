"""Unit tests for the health server."""

import json
import urllib.request

from pipeline.health import HealthCheckRegistry, HealthServer


class TestHealthCheckRegistry:
    def test_empty_registry_is_healthy(self):
        registry = HealthCheckRegistry()
        healthy, details = registry.evaluate()
        assert healthy is True
        assert details == {}

    def test_passing_check(self):
        registry = HealthCheckRegistry()
        registry.register("test", lambda: (True, "ok"))
        healthy, details = registry.evaluate()
        assert healthy is True
        assert details["test"]["healthy"] is True

    def test_failing_check(self):
        registry = HealthCheckRegistry()
        registry.register("test", lambda: (False, "not connected"))
        healthy, details = registry.evaluate()
        assert healthy is False
        assert details["test"]["healthy"] is False
        assert details["test"]["detail"] == "not connected"

    def test_mixed_checks(self):
        registry = HealthCheckRegistry()
        registry.register("good", lambda: (True, "ok"))
        registry.register("bad", lambda: (False, "broken"))
        healthy, details = registry.evaluate()
        assert healthy is False

    def test_exception_in_check(self):
        registry = HealthCheckRegistry()

        def bad_check():
            raise RuntimeError("boom")

        registry.register("crasher", bad_check)
        healthy, details = registry.evaluate()
        assert healthy is False
        assert "boom" in details["crasher"]["detail"]


class TestHealthServer:
    def _get(self, port, path):
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_healthz_returns_200(self):
        server = HealthServer(port=0)
        server.start()
        # Get the actual port assigned
        port = server._server.server_address[1]
        try:
            status, body = self._get(port, "/healthz")
            assert status == 200
            assert body["status"] == "ok"
        finally:
            server.stop()

    def test_readyz_healthy(self):
        registry = HealthCheckRegistry()
        registry.register("kafka", lambda: (True, "connected"))
        server = HealthServer(port=0, registry=registry)
        server.start()
        port = server._server.server_address[1]
        try:
            status, body = self._get(port, "/readyz")
            assert status == 200
            assert body["status"] == "ready"
        finally:
            server.stop()

    def test_readyz_unhealthy(self):
        registry = HealthCheckRegistry()
        registry.register("kafka", lambda: (False, "disconnected"))
        server = HealthServer(port=0, registry=registry)
        server.start()
        port = server._server.server_address[1]
        try:
            status, body = self._get(port, "/readyz")
            assert status == 503
            assert body["status"] == "not_ready"
        finally:
            server.stop()

    def test_404_for_unknown_path(self):
        server = HealthServer(port=0)
        server.start()
        port = server._server.server_address[1]
        try:
            status, body = self._get(port, "/unknown")
            assert status == 404
        finally:
            server.stop()
