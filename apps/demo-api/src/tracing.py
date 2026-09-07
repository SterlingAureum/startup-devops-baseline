import os
from contextlib import contextmanager
from typing import Generator, Mapping
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

from .runtime_identity import runtime_identity


DEFAULT_OTLP_TRACES_ENDPOINT = (
    "http://observability-otel-collector.observability.svc.cluster.local:4318/"
    "v1/traces"
)
QUIET_HTTP_PATHS = frozenset({"/health", "/ready", "/metrics"})
DATABASE_SPAN_NAMES = {
    "health": "postgresql health",
    "marker.write": "postgresql marker.write",
    "marker.read": "postgresql marker.read",
}
FORBIDDEN_AMBIENT_EXPORTER_CREDENTIALS = (
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_CLIENT_KEY",
    "OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY",
    "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
    "_OTEL_PYTHON_EXPORTER_OTLP_HTTP_TRACES_CREDENTIAL_PROVIDER",
)
_CONFIGURED_PROVIDER: TracerProvider | None = None


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def tracing_enabled() -> bool:
    return _enabled(os.getenv("TRACING_ENABLED", "false"))


def _validated_endpoint() -> str:
    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        DEFAULT_OTLP_TRACES_ENDPOINT,
    )
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("OTLP traces endpoint must be an HTTP(S) URL without credentials, query, or fragment")
    return endpoint


def _validated_timeout() -> float:
    try:
        timeout = float(os.getenv("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", "5"))
    except ValueError as error:
        raise RuntimeError("OTLP traces timeout must be numeric") from error
    if timeout <= 0 or timeout > 30:
        raise RuntimeError("OTLP traces timeout must be greater than zero and at most 30 seconds")
    return timeout


def tracing_resource() -> Resource:
    return Resource(attributes=runtime_identity())


def _reject_ambient_exporter_credentials() -> None:
    configured = [
        name
        for name in FORBIDDEN_AMBIENT_EXPORTER_CREDENTIALS
        if os.getenv(name, "").strip()
    ]
    if configured:
        raise RuntimeError(
            "v0.11.6.2.0 does not accept ambient OTLP credential or certificate settings"
        )


def configure_tracing() -> TracerProvider | None:
    """Configure one OTLP exporter only when explicitly enabled."""

    global _CONFIGURED_PROVIDER
    if not tracing_enabled():
        return None
    if _CONFIGURED_PROVIDER is not None:
        return _CONFIGURED_PROVIDER

    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    if protocol != "http/protobuf":
        raise RuntimeError("demo-api tracing supports only OTLP http/protobuf")
    _reject_ambient_exporter_credentials()

    provider = TracerProvider(resource=tracing_resource())
    exporter = OTLPSpanExporter(
        endpoint=_validated_endpoint(),
        timeout=_validated_timeout(),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _CONFIGURED_PROVIDER = provider
    return provider


def _request_carrier(headers: list[tuple[bytes, bytes]]) -> Mapping[str, str]:
    carrier: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        if name in {"traceparent", "tracestate"}:
            carrier[name] = raw_value.decode("latin-1")
    return carrier


def extracted_http_context(headers: list[tuple[bytes, bytes]]) -> Context:
    """Extract only W3C Trace Context; baggage is intentionally not accepted."""

    return TraceContextTextMapPropagator().extract(_request_carrier(headers))


@contextmanager
def http_server_span(
    *,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]],
    tracer: Tracer | None = None,
) -> Generator[Span | None, None, None]:
    if not tracing_enabled() or path in QUIET_HTTP_PATHS:
        yield None
        return

    active_tracer = tracer or trace.get_tracer("startup-devops-baseline.demo-api")
    with active_tracer.start_as_current_span(
        f"{method} HTTP",
        context=extracted_http_context(headers),
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


def finish_http_server_span(
    span: Span | None,
    *,
    method: str,
    route: str,
    status_code: int,
) -> None:
    if span is None:
        return
    span.update_name(f"{method} {route}")
    span.set_attribute("http.request.method", method)
    span.set_attribute("http.route", route)
    span.set_attribute("http.response.status_code", status_code)
    if status_code >= 500:
        span.set_status(Status(StatusCode.ERROR))


@contextmanager
def database_client_span(
    operation: str,
    *,
    enabled: bool = True,
    tracer: Tracer | None = None,
) -> Generator[Span | None, None, None]:
    if operation not in DATABASE_SPAN_NAMES:
        raise ValueError("database tracing operation is not allowlisted")
    if not enabled or not tracing_enabled():
        yield None
        return

    active_tracer = tracer or trace.get_tracer("startup-devops-baseline.demo-api")
    with active_tracer.start_as_current_span(
        DATABASE_SPAN_NAMES[operation],
        kind=SpanKind.CLIENT,
        attributes={
            "db.system.name": "postgresql",
            "db.operation.name": operation,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception:
            span.set_status(Status(StatusCode.ERROR))
            raise
