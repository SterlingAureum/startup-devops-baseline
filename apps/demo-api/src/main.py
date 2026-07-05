import os
import time
from typing import Dict, Any

from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

APP_NAME = os.getenv("APP_NAME", "demo-api")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
APP_ENV = os.getenv("APP_ENV", "local")
START_TIME = time.time()

REQUEST_COUNT = Counter(
    "demo_api_requests_total",
    "Total number of HTTP requests handled by demo-api.",
    ["path"],
)

REQUEST_LATENCY = Histogram(
    "demo_api_request_duration_seconds",
    "HTTP request latency for demo-api.",
    ["path"],
)

app = FastAPI(
    title="startup-devops-baseline demo-api",
    version=APP_VERSION,
    description="Minimal API workload for the startup DevOps baseline.",
)


def app_info() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "environment": APP_ENV,
        "uptime_seconds": round(time.time() - START_TIME, 3),
    }


@app.get("/")
def root() -> Dict[str, Any]:
    path = "/"
    start = time.time()
    try:
        REQUEST_COUNT.labels(path=path).inc()
        return {
            "message": "startup-devops-baseline demo-api is running",
            "service": app_info(),
        }
    finally:
        REQUEST_LATENCY.labels(path=path).observe(time.time() - start)


@app.get("/health")
def health() -> Dict[str, str]:
    path = "/health"
    start = time.time()
    try:
        REQUEST_COUNT.labels(path=path).inc()
        return {"status": "ok"}
    finally:
        REQUEST_LATENCY.labels(path=path).observe(time.time() - start)


@app.get("/ready")
def ready() -> Dict[str, str]:
    path = "/ready"
    start = time.time()
    try:
        REQUEST_COUNT.labels(path=path).inc()
        return {"status": "ready"}
    finally:
        REQUEST_LATENCY.labels(path=path).observe(time.time() - start)


@app.get("/version")
def version() -> Dict[str, Any]:
    path = "/version"
    start = time.time()
    try:
        REQUEST_COUNT.labels(path=path).inc()
        return app_info()
    finally:
        REQUEST_LATENCY.labels(path=path).observe(time.time() - start)


@app.get("/metrics")
def metrics() -> Response:
    REQUEST_COUNT.labels(path="/metrics").inc()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
