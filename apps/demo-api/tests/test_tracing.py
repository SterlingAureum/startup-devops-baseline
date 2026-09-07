import json
import logging
import os
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from src import tracing
from src.logging_config import JsonLineFormatter
from src.tracing import (
    database_client_span,
    finish_http_server_span,
    http_server_span,
    tracing_resource,
)


class TracingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("demo-api-tests")

    def tearDown(self) -> None:
        self.provider.shutdown()

    @staticmethod
    def _record() -> logging.LogRecord:
        return logging.LogRecord(
            name="demo_api",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="http_request_completed",
            args=(),
            exc_info=None,
        )

    def test_disabled_tracing_creates_no_span(self) -> None:
        with patch.dict(os.environ, {"TRACING_ENABLED": "false"}, clear=False):
            with http_server_span(
                method="GET",
                path="/version",
                headers=[],
                tracer=self.tracer,
            ) as span:
                self.assertIsNone(span)

        self.assertEqual(self.exporter.get_finished_spans(), ())

    def test_disabled_configuration_creates_no_exporter_or_provider(self) -> None:
        with patch.dict(os.environ, {"TRACING_ENABLED": "false"}, clear=True):
            with patch.object(tracing, "OTLPSpanExporter") as exporter:
                with patch.object(tracing, "_CONFIGURED_PROVIDER", None):
                    self.assertIsNone(tracing.configure_tracing())
                    self.assertIsNone(tracing._CONFIGURED_PROVIDER)
        exporter.assert_not_called()

    def test_unsafe_export_endpoint_is_rejected_before_exporter_creation(self) -> None:
        environment = {
            "TRACING_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "https://user:secret@example.invalid/v1/traces?token=secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(tracing, "OTLPSpanExporter") as exporter:
                with patch.object(tracing, "_CONFIGURED_PROVIDER", None):
                    with self.assertRaisesRegex(RuntimeError, "without credentials"):
                        tracing.configure_tracing()
        exporter.assert_not_called()

    def test_ambient_exporter_credentials_are_rejected(self) -> None:
        environment = {
            "TRACING_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "authorization=secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(tracing, "OTLPSpanExporter") as exporter:
                with patch.object(tracing, "_CONFIGURED_PROVIDER", None):
                    with self.assertRaisesRegex(RuntimeError, "ambient OTLP credential"):
                        tracing.configure_tracing()
        exporter.assert_not_called()

    def test_w3c_parent_server_database_and_log_correlation(self) -> None:
        trace_id = "0af7651916cd43dd8448eb211c80319c"
        parent_span_id = "b7ad6b7169203331"
        headers = [
            (
                b"traceparent",
                f"00-{trace_id}-{parent_span_id}-01".encode("ascii"),
            ),
            (b"authorization", b"Bearer sensitive"),
            (b"baggage", b"password=sensitive"),
        ]
        formatter = JsonLineFormatter()

        with patch.dict(os.environ, {"TRACING_ENABLED": "true"}, clear=False):
            with http_server_span(
                method="GET",
                path="/db/health",
                headers=headers,
                tracer=self.tracer,
            ) as server_span:
                finish_http_server_span(
                    server_span,
                    method="GET",
                    route="/db/health",
                    status_code=200,
                )
                with database_client_span("health", tracer=self.tracer):
                    payload = json.loads(formatter.format(self._record()))

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        database_span, server_span = spans
        self.assertEqual(server_span.kind, SpanKind.SERVER)
        self.assertEqual(server_span.name, "GET /db/health")
        self.assertEqual(format(server_span.context.trace_id, "032x"), trace_id)
        self.assertEqual(format(server_span.parent.span_id, "016x"), parent_span_id)
        self.assertEqual(server_span.attributes["http.route"], "/db/health")
        self.assertEqual(database_span.kind, SpanKind.CLIENT)
        self.assertEqual(database_span.name, "postgresql health")
        self.assertEqual(database_span.parent.span_id, server_span.context.span_id)
        self.assertEqual(database_span.attributes["db.system.name"], "postgresql")
        self.assertNotIn("db.statement", database_span.attributes)
        self.assertEqual(payload["trace_id"], trace_id)
        self.assertEqual(payload["span_id"], format(database_span.context.span_id, "016x"))
        self.assertNotIn("sensitive", str(server_span.attributes))
        self.assertNotIn("sensitive", str(database_span.attributes))

    def test_probe_and_metrics_paths_do_not_create_success_spans(self) -> None:
        with patch.dict(os.environ, {"TRACING_ENABLED": "true"}, clear=False):
            for path in ("/health", "/ready", "/metrics"):
                with http_server_span(
                    method="GET",
                    path=path,
                    headers=[],
                    tracer=self.tracer,
                ) as span:
                    self.assertIsNone(span)

        self.assertEqual(self.exporter.get_finished_spans(), ())

    def test_server_and_database_failures_set_error_without_exception_data(self) -> None:
        with patch.dict(os.environ, {"TRACING_ENABLED": "true"}, clear=False):
            with http_server_span(
                method="GET",
                path="/db/health",
                headers=[],
                tracer=self.tracer,
            ) as server_span:
                finish_http_server_span(
                    server_span,
                    method="GET",
                    route="/db/health",
                    status_code=503,
                )
                with self.assertRaisesRegex(RuntimeError, "secret-password"):
                    with database_client_span("health", tracer=self.tracer):
                        raise RuntimeError("secret-password")

        database_span, server_span = self.exporter.get_finished_spans()
        self.assertEqual(database_span.status.status_code, StatusCode.ERROR)
        self.assertEqual(server_span.status.status_code, StatusCode.ERROR)
        for span in (database_span, server_span):
            self.assertEqual(span.events, ())
            self.assertNotIn("secret-password", str(span.attributes))

    def test_log_ids_are_omitted_without_an_active_span(self) -> None:
        payload = json.loads(JsonLineFormatter().format(self._record()))
        self.assertNotIn("trace_id", payload)
        self.assertNotIn("span_id", payload)

    def test_resource_reuses_canonical_release_identity(self) -> None:
        identity = {
            "APP_NAME": "demo-api",
            "APP_VERSION": "sha-7654321",
            "APP_ENV": "local",
            "PLATFORM_RELEASE_ID": "demo-api-local-sha-7654321",
            "PLATFORM_SOURCE_COMMIT": "7654321abcdef",
            "CONTAINER_IMAGE_DIGEST": "sha256:" + ("b" * 64),
            "OTEL_RESOURCE_ATTRIBUTES": "customer.secret=must-not-appear",
        }
        with patch.dict(os.environ, identity, clear=True):
            attributes = tracing_resource().attributes

        self.assertEqual(attributes["service.name"], "demo-api")
        self.assertEqual(attributes["service.version"], "sha-7654321")
        self.assertEqual(attributes["deployment.environment.name"], "local")
        self.assertEqual(
            attributes["platform.release.id"],
            "demo-api-local-sha-7654321",
        )
        self.assertEqual(
            attributes["container.image.digest"],
            "sha256:" + ("b" * 64),
        )
        self.assertNotIn("customer.secret", attributes)

    def test_database_operation_names_are_allowlisted(self) -> None:
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            with database_client_span("SELECT secret FROM customer"):
                pass


if __name__ == "__main__":
    unittest.main()
