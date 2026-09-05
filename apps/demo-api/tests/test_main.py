import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

from src import main

## test/prove-release-supersede-a-4
## test/prove-release-supersede-b-4

class ApplicationEndpointTests(unittest.TestCase):
    @staticmethod
    def request(path: str = "/version", fault_token: str | None = None) -> Request:
        headers = [] if fault_token is None else [(b"x-rehearsal-fault", fault_token.encode())]
        return Request({"type": "http", "method": "GET", "path": path,
                        "headers": headers, "route": type("Route", (), {"path": path})()})

    @staticmethod
    def record_http_request(
        method: str,
        status_code: int,
        route: str | None,
        raw_path: str,
    ) -> None:
        scope = {
            "type": "http",
            "method": method,
            "path": raw_path,
            "headers": [],
        }
        if route is not None:
            scope["route"] = type("Route", (), {"path": route})()

        request = Request(scope)

        async def call_next(_: Request) -> Response:
            return Response(status_code=status_code)

        asyncio.run(main.record_http_metrics(request, call_next))

    def test_health_reports_ok(self) -> None:
        self.assertEqual(main.health(), {"status": "ok"})

    def test_version_fault_requires_mode_and_exact_token(self) -> None:
        with patch.object(main, 'REHEARSAL_FAULT_MODE', 'availability-503'), \
                patch.object(main, 'REHEARSAL_FAULT_TOKEN_SHA256', 'a' * 64), \
                patch('src.main.availability_failure_requested', return_value=True) as requested:
            with self.assertRaises(HTTPException) as raised:
                main.version(self.request(fault_token='private'))
        self.assertEqual(raised.exception.status_code, 503)
        requested.assert_called_once_with('availability-503', 'a' * 64, 'private')

    def test_version_without_matching_fault_is_healthy(self) -> None:
        with patch('src.main.availability_failure_requested', return_value=False):
            response = main.version(self.request())
        self.assertEqual(response['version'], main.APP_VERSION)

    def test_root_includes_service_identity(self) -> None:
        response = main.root()

        self.assertIn("service", response)
        self.assertEqual(response["service"]["name"], main.APP_NAME)
        self.assertEqual(response["service"]["version"], main.APP_VERSION)
        self.assertEqual(response["service"]["environment"], main.APP_ENV)

    def test_ready_without_database_dependency(self) -> None:
        with patch("src.main.database_enabled", return_value=False):
            self.assertEqual(
                main.ready(),
                {"status": "ready", "database": "disabled"},
            )

    def test_ready_with_healthy_database_dependency(self) -> None:
        with patch("src.main.database_enabled", return_value=True):
            with patch(
                "src.main.database_health",
                return_value={"status": "ok"},
            ) as database_health:
                self.assertEqual(
                    main.ready(),
                    {"status": "ready", "database": "ok"},
                )
                database_health.assert_called_once_with(traced=False)

    def test_ready_sanitizes_database_failure(self) -> None:
        with patch("src.main.database_enabled", return_value=True):
            with patch(
                "src.main.database_health",
                side_effect=RuntimeError("sensitive connection detail"),
            ):
                with self.assertRaises(HTTPException) as raised:
                    main.ready()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            raised.exception.detail,
            "PostgreSQL dependency is unavailable",
        )

    def test_metrics_endpoint_returns_prometheus_content(self) -> None:
        self.record_http_request("GET", 200, "/health", "/health")
        response = main.metrics()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "text/plain",
            response.media_type,
        )
        self.assertIn(
            b"demo_api_http_requests_total",
            response.body,
        )
        self.assertIn(b'method="GET"', response.body)
        self.assertIn(b'route="/health"', response.body)
        self.assertIn(b'status_class="2xx"', response.body)

    def test_unmatched_routes_use_one_bounded_label(self) -> None:
        self.record_http_request(
            "UNBOUNDED-METHOD",
            404,
            None,
            "/customer/12345?token=sensitive",
        )

        metrics = main.metrics().body
        self.assertIn(b'method="OTHER"', metrics)
        self.assertIn(b'route="__unmatched__"', metrics)
        self.assertIn(b'status_class="4xx"', metrics)
        self.assertNotIn(b"/customer/12345", metrics)
        self.assertNotIn(b"token=sensitive", metrics)

    def test_version_request_emits_bounded_structured_log(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/version",
            "query_string": b"token=sensitive",
            "headers": [(b"authorization", b"Bearer sensitive")],
            "route": type("Route", (), {"path": "/version"})(),
        }
        request = Request(scope)

        async def call_next(_: Request) -> Response:
            return Response(status_code=200)

        with patch("src.main.emit_log") as emitted:
            asyncio.run(main.record_http_metrics(request, call_next))

        emitted.assert_called_once()
        arguments = emitted.call_args.kwargs
        self.assertEqual(emitted.call_args.args, ("http_request_completed",))
        self.assertEqual(arguments["fields"]["http.request.method"], "GET")
        self.assertEqual(arguments["fields"]["http.route"], "/version")
        self.assertEqual(arguments["fields"]["http.response.status_code"], 200)
        self.assertEqual(arguments["fields"]["outcome"], "success")
        self.assertNotIn("sensitive", str(arguments))

    def test_successful_probe_and_metrics_requests_are_quiet(self) -> None:
        async def call_next(_: Request) -> Response:
            return Response(status_code=200)

        for route in ("/health", "/ready", "/metrics"):
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": route,
                    "headers": [],
                    "route": type("Route", (), {"path": route})(),
                }
            )
            with patch("src.main.emit_log") as emitted:
                asyncio.run(main.record_http_metrics(request, call_next))
            emitted.assert_not_called()

    def test_failed_probe_is_logged_without_raw_request_data(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/ready",
                "query_string": b"password=sensitive",
                "headers": [],
                "route": type("Route", (), {"path": "/ready"})(),
            }
        )

        async def call_next(_: Request) -> Response:
            return Response(status_code=503)

        with patch("src.main.emit_log") as emitted:
            asyncio.run(main.record_http_metrics(request, call_next))

        fields = emitted.call_args.kwargs["fields"]
        self.assertEqual(fields["http.route"], "/ready")
        self.assertEqual(fields["outcome"], "failure")
        self.assertNotIn("sensitive", str(fields))

    def test_database_metrics_record_success_and_failure_without_details(self) -> None:
        with patch("src.main.database_enabled", return_value=True):
            with patch("src.main.database_health", return_value={"status": "ok"}):
                self.assertEqual(main.ready()["status"], "ready")

            with patch(
                "src.main.database_health",
                side_effect=RuntimeError("postgresql://secret-user:secret-password@db"),
            ):
                with self.assertRaises(HTTPException):
                    main.db_health()

        metrics = main.metrics().body
        self.assertIn(
            b'demo_api_dependency_checks_total{dependency="postgresql",outcome="success"}',
            metrics,
        )
        self.assertIn(
            b'demo_api_dependency_checks_total{dependency="postgresql",outcome="failure"}',
            metrics,
        )
        self.assertNotIn(b"secret-password", metrics)


if __name__ == "__main__":
    unittest.main()
