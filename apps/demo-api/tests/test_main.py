import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

from src import main

## test/prove-release-supersede-a-4
## test/prove-release-supersede-b-4

class ApplicationEndpointTests(unittest.TestCase):
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
            ):
                self.assertEqual(
                    main.ready(),
                    {"status": "ready", "database": "ok"},
                )

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
