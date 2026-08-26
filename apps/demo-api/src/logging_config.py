import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Mapping


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


def _runtime_identity() -> dict[str, str]:
    service_name = os.getenv("APP_NAME", "demo-api")
    service_version = os.getenv("APP_VERSION", "0.1.0")
    return {
        "service.name": service_name,
        "service.version": service_version,
        "deployment.environment.name": os.getenv("APP_ENV", "local"),
        "platform.release.id": os.getenv(
            "PLATFORM_RELEASE_ID",
            f"{service_name}-local-{service_version}",
        ),
        "platform.source.commit": os.getenv(
            "PLATFORM_SOURCE_COMMIT",
            "local-unavailable",
        ),
        "container.image.digest": os.getenv(
            "CONTAINER_IMAGE_DIGEST",
            "local-unpinned",
        ),
    }


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
            **_runtime_identity(),
        }

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
