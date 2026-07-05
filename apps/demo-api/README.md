# demo-api

`demo-api` is a minimal FastAPI workload for the `startup-devops-baseline` repository.

It exists to validate the local DevOps and GitOps baseline. The application is intentionally small so the repository can focus on platform workflow, Kubernetes deployment, ingress, observability, validation, and rollback scenarios.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `/` | Basic service information |
| `/health` | Liveness check |
| `/ready` | Readiness check |
| `/version` | Version and environment information |
| `/metrics` | Prometheus-style metrics |

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

## Next Step

The next repository stage will add a Helm chart and Argo CD application definition so this service can be deployed through GitOps.
