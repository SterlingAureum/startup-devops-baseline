#!/usr/bin/env python3
"""Generate the bounded OTLP/JSON trace used by local tracing acceptance."""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any


TRACE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
SPAN_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")


def _validated_identifier(value: str, pattern: re.Pattern[str], name: str) -> str:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must be an exact hexadecimal OTLP identifier")
    if int(value, 16) == 0:
        raise ValueError(f"{name} must not be all zeroes")
    return value.lower()


def build_payload(
    trace_id: str,
    span_id: str,
    *,
    start_time_unix_nano: int | None = None,
) -> dict[str, Any]:
    """Return one valid OTLP/JSON ExportTraceServiceRequest payload."""

    normalized_trace_id = _validated_identifier(
        trace_id, TRACE_ID_PATTERN, "trace_id"
    )
    normalized_span_id = _validated_identifier(span_id, SPAN_ID_PATTERN, "span_id")
    start = time.time_ns() if start_time_unix_nano is None else start_time_unix_nano
    if start <= 0:
        raise ValueError("start_time_unix_nano must be positive")

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {
                                "stringValue": "v0.11.6.2.1.1-acceptance"
                            },
                        },
                        {
                            "key": "deployment.environment.name",
                            "value": {"stringValue": "local"},
                        },
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "startup-devops-baseline.acceptance",
                            "version": "v0.11.6.2.1.1",
                        },
                        "spans": [
                            {
                                "traceId": normalized_trace_id,
                                "spanId": normalized_span_id,
                                "name": "v0.11.6.2.1.1.synthetic.collector-tempo",
                                "kind": 1,
                                "startTimeUnixNano": str(start),
                                "endTimeUnixNano": str(start + 1_000_000),
                                "attributes": [
                                    {
                                        "key": "test.run_id",
                                        "value": {
                                            "stringValue": normalized_trace_id
                                        },
                                    }
                                ],
                                "status": {"code": 1},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--span-id", required=True)
    args = parser.parse_args()
    try:
        payload = build_payload(args.trace_id, args.span_id)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
