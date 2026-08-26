import logging
import os
import time
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .database import database_enabled, database_health
from .logging_config import emit_log

APP_NAME = os.getenv("APP_NAME", "demo-api")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
APP_ENV = os.getenv("APP_ENV", "local")
START_TIME = time.time()

HTTP_REQUESTS = Counter(
    "demo_api_http_requests_total",
    "Total number of HTTP requests handled by demo-api.",
    ["method", "route", "status_class"],
)

HTTP_REQUEST_DURATION = Histogram(
    "demo_api_http_request_duration_seconds",
    "HTTP request latency for demo-api.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

DEPENDENCY_CHECKS = Counter(
    "demo_api_dependency_checks_total",
    "Total number of bounded dependency health checks.",
    ["dependency", "outcome"],
)

DEPENDENCY_CHECK_DURATION = Histogram(
    "demo_api_dependency_check_duration_seconds",
    "Dependency health-check latency.",
    ["dependency"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
ALLOWED_ROUTES = frozenset({"/", "/health", "/ready", "/db/health", "/version", "/metrics"})
QUIET_SUCCESS_ROUTES = frozenset({"/health", "/ready", "/metrics"})

app = FastAPI(
    title="startup-devops-baseline demo-api",
    version=APP_VERSION,
    description="Minimal API workload for the startup DevOps baseline.",
)


def _normalized_method(method: str) -> str:
    candidate = method.upper()
    return candidate if candidate in ALLOWED_METHODS else "OTHER"


def _normalized_route(request: Request) -> str:
    route = request.scope.get("route")
    candidate = getattr(route, "path", None)
    return candidate if candidate in ALLOWED_ROUTES else "__unmatched__"


def _status_class(status_code: int) -> str:
    if 200 <= status_code <= 599:
        return f"{status_code // 100}xx"
    return "unknown"


@app.middleware("http")
async def record_http_metrics(request: Request, call_next: Any) -> Response:
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        method = _normalized_method(request.method)
        route = _normalized_route(request)
        duration_seconds = time.perf_counter() - start
        HTTP_REQUESTS.labels(
            method=method,
            route=route,
            status_class=_status_class(status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(
            duration_seconds
        )
        if status_code >= 400 or route not in QUIET_SUCCESS_ROUTES:
            severity = logging.INFO
            if status_code >= 500:
                severity = logging.ERROR
            elif status_code >= 400:
                severity = logging.WARNING
            emit_log(
                "http_request_completed",
                severity=severity,
                fields={
                    "http.request.method": method,
                    "http.route": route,
                    "http.response.status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                    "outcome": "success" if status_code < 400 else "failure",
                },
            )


def _record_database_disabled() -> None:
    DEPENDENCY_CHECKS.labels(dependency="postgresql", outcome="disabled").inc()


def _observed_database_health() -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        result = database_health()
    except RuntimeError:
        DEPENDENCY_CHECKS.labels(dependency="postgresql", outcome="failure").inc()
        raise
    else:
        DEPENDENCY_CHECKS.labels(dependency="postgresql", outcome="success").inc()
        return result
    finally:
        DEPENDENCY_CHECK_DURATION.labels(dependency="postgresql").observe(
            time.perf_counter() - start
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
    return {
        "message": "startup-devops-baseline demo-api is running",
        "service": app_info(),
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> Dict[str, Any]:
    if not database_enabled():
        _record_database_disabled()
        return {"status": "ready", "database": "disabled"}

    try:
        database = _observed_database_health()
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL dependency is unavailable",
        ) from error

    return {"status": "ready", "database": database["status"]}


@app.get("/db/health")
def db_health() -> Dict[str, Any]:
    if not database_enabled():
        _record_database_disabled()
        return {"status": "disabled"}

    try:
        return _observed_database_health()
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL dependency is unavailable",
        ) from error


@app.get("/version")
def version() -> Dict[str, Any]:
    return app_info()


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
