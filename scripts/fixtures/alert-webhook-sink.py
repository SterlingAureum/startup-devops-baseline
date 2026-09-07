#!/usr/bin/env python3
"""Bounded in-memory Alertmanager webhook sink for lifecycle drills."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Lock
import time
from typing import Any


HOST = os.environ.get("SINK_HOST", "0.0.0.0")
PORT = int(os.environ.get("SINK_PORT", "8080"))
MAX_BODY_BYTES = int(os.environ.get("SINK_MAX_BODY_BYTES", "1048576"))
MAX_EVENTS = int(os.environ.get("SINK_MAX_EVENTS", "500"))
ALLOWED_EVENT_PATHS = {"/critical", "/warning"}

events: list[dict[str, Any]] = []
events_lock = Lock()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "alert-lifecycle-drill-sink/1"

    def log_message(self, format_string: str, *args: object) -> None:
        print(
            json.dumps(
                {
                    "timestamp": time.time(),
                    "remote": self.client_address[0],
                    "message": format_string % args,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def respond(self, status: int, value: Any) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/health":
            self.respond(200, {"status": "ok"})
            return
        if self.path == "/events":
            with events_lock:
                snapshot = list(events)
            self.respond(200, {"events": snapshot})
            return
        self.respond(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/reset":
            with events_lock:
                events.clear()
            self.respond(200, {"status": "reset"})
            return
        if self.path not in ALLOWED_EVENT_PATHS:
            self.respond(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.respond(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self.respond(413, {"error": "invalid body size"})
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.respond(400, {"error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self.respond(400, {"error": "expected JSON object"})
            return

        event = {
            "receivedAt": time.time(),
            "path": self.path,
            "payload": payload,
        }
        with events_lock:
            events.append(event)
            if len(events) > MAX_EVENTS:
                del events[: len(events) - MAX_EVENTS]

        print(json.dumps(event, separators=(",", ":"), sort_keys=True), flush=True)
        self.respond(200, {"status": "accepted"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(json.dumps({"status": "listening", "host": HOST, "port": PORT}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
