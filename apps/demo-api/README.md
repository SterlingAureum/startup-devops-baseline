# demo-api

`demo-api` is a minimal FastAPI workload for the `startup-devops-baseline` repository.

It validates the local DevOps and GitOps baseline and, in the AWS environment,
the application-to-PostgreSQL path and reconnection behavior during a
CloudNativePG primary failover. The application remains intentionally small so
the repository can focus on platform workflows.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `/` | Basic service information |
| `/health` | Liveness check |
| `/ready` | Readiness check |
| `/db/health` | Sanitized PostgreSQL dependency status |
| `/version` | Version and environment information |
| `/metrics` | Prometheus-style metrics |

`/health` is process-only. `/ready` includes PostgreSQL when
`DATABASE_ENABLED=true`. `/db/health` never returns a password, URI, or DSN.

The v0.11.2 Prometheus contract exposes bounded HTTP and dependency signals:

| Metric | Labels |
| --- | --- |
| `demo_api_http_requests_total` | `method`, `route`, `status_class` |
| `demo_api_http_request_duration_seconds` | `method`, `route` |
| `demo_api_dependency_checks_total` | `dependency`, `outcome` |
| `demo_api_dependency_check_duration_seconds` | `dependency` |

Unknown routes collapse to `__unmatched__`; raw URLs, query strings, database
parameters, and exception details are never exported as labels.

## Local Development

Run locally with Python:

```bash
cd apps/demo-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080
```

Test the service:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/version
curl http://localhost:8080/metrics
```

Run the unit tests with the same isolated Docker stage used by CI:

```bash
docker build --target test -t demo-api-ci-test:unit .
```

## Docker Build

Build the image:

```bash
cd apps/demo-api
docker build -t startup-devops-baseline/demo-api:0.1.0 .
```

Run the image:

```bash
docker run --rm -p 8080:8080 startup-devops-baseline/demo-api:0.1.0
```

Test the container:

```bash
curl http://localhost:8080/health
```

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `demo-api` | Service name |
| `APP_VERSION` | `0.1.0` | Application version |
| `APP_ENV` | `local` | Runtime environment |
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL readiness and health checks |
| `DATABASE_URL` | none | PostgreSQL URI supplied from a Kubernetes Secret |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | `3` | Timeout for one connection attempt |
| `DATABASE_RETRY_ATTEMPTS` | `3` | Bounded retry count |
| `DATABASE_RETRY_DELAY_SECONDS` | `1` | Delay between retries |

The local environment leaves database integration disabled. The AWS Helm values
enable it and reference `startup-apps/demo-api-postgresql`.

## Internal Marker CLI

The primary-failover test writes and reads validation markers through the same
application database module without exposing a public write endpoint:

```bash
python -m src.database health
python -m src.database write-marker --id example --value verified
python -m src.database read-marker --id example
```
