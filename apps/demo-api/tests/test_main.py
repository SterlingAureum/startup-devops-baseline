import unittest
from unittest.mock import patch

from fastapi import HTTPException

from src import main

## test/prove-release-supersede-a

class ApplicationEndpointTests(unittest.TestCase):
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
        response = main.metrics()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "text/plain",
            response.media_type,
        )
        self.assertIn(
            b"demo_api_requests_total",
            response.body,
        )


if __name__ == "__main__":
    unittest.main()
