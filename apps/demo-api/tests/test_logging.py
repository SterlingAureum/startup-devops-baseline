import json
import logging
import unittest
from unittest.mock import patch

from src.logging_config import JsonLineFormatter


class StructuredLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = JsonLineFormatter()

    def test_formatter_emits_required_release_identity(self) -> None:
        record = logging.LogRecord(
            name="demo_api",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="http_request_completed",
            args=(),
            exc_info=None,
        )
        record.structured_fields = {
            "http.request.method": "GET",
            "http.route": "/version",
            "http.response.status_code": 200,
            "duration_ms": 1.25,
            "outcome": "success",
        }

        environment = {
            "APP_NAME": "demo-api",
            "APP_VERSION": "sha-0123456",
            "APP_ENV": "local",
            "PLATFORM_RELEASE_ID": "demo-api-local-sha-0123456",
            "PLATFORM_SOURCE_COMMIT": "0123456789abcdef",
            "CONTAINER_IMAGE_DIGEST": "sha256:" + ("a" * 64),
        }
        with patch.dict("os.environ", environment, clear=True):
            line = self.formatter.format(record)

        self.assertNotIn("\n", line)
        payload = json.loads(line)
        self.assertEqual(payload["severity"], "INFO")
        self.assertEqual(payload["message"], "http_request_completed")
        self.assertEqual(payload["service.name"], "demo-api")
        self.assertEqual(payload["service.version"], "sha-0123456")
        self.assertEqual(payload["deployment.environment.name"], "local")
        self.assertEqual(
            payload["platform.release.id"],
            "demo-api-local-sha-0123456",
        )
        self.assertEqual(
            payload["container.image.digest"],
            "sha256:" + ("a" * 64),
        )
        self.assertEqual(payload["http.route"], "/version")
        self.assertNotIn("trace_id", payload)
        self.assertNotIn("span_id", payload)

    def test_exception_message_is_not_exported(self) -> None:
        try:
            raise RuntimeError("postgresql://user:secret-password@example.invalid")
        except RuntimeError:
            import sys

            exception = sys.exc_info()

        record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="unsafe %s",
            args=("secret-password",),
            exc_info=exception,
        )
        line = self.formatter.format(record)

        self.assertNotIn("secret-password", line)
        self.assertEqual(json.loads(line)["message"], "unhandled_exception")

    def test_structured_fields_cannot_override_required_identity(self) -> None:
        record = logging.LogRecord(
            name="demo_api",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="identity_check",
            args=(),
            exc_info=None,
        )
        record.structured_fields = {
            "service.name": "forged-service",
            "platform.release.id": "forged-release",
        }

        payload = json.loads(self.formatter.format(record))

        self.assertEqual(payload["service.name"], "demo-api")
        self.assertNotEqual(payload["platform.release.id"], "forged-release")


if __name__ == "__main__":
    unittest.main()
