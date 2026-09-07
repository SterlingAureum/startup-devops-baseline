import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

from opentelemetry import trace

from .runtime_identity import runtime_identity


REQUIRED_IDENTITY_FIELDS = (
    "service.name",
    "service.version",
    "deployment.environment.name",
    "platform.release.id",
    "platform.source.commit",
    "container.image.digest",
)

LOGGER = logging.getLogger("demo_api")
LOGGER.addHandler(logging.NullHandler())


def _timestamp(created: float) -> str:
    value = datetime.fromtimestamp(created, timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonLineFormatter(logging.Formatter):
    """Render one bounded JSON object for every process log record."""

    def format(self, record: logging.LogRecord) -> str:
        message = "unhandled_exception" if record.exc_info else record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": _timestamp(record.created),
            "severity": record.levelname.upper(),
            "message": message,
            **runtime_identity(),
        }

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")

        fields = getattr(record, "structured_fields", {})
        if isinstance(fields, Mapping):
            for key, value in fields.items():
                if key not in payload:
                    payload[str(key)] = value

        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLineFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)

    for logger_name in ("demo_api", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.INFO)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
    access_logger.disabled = True


def emit_log(
    message: str,
    *,
    severity: int = logging.INFO,
    fields: Mapping[str, Any] | None = None,
) -> None:
    LOGGER.log(
        severity,
        message,
        extra={"structured_fields": dict(fields or {})},
    )
