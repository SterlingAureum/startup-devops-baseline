## Local Development Quick Start

### 1. Create the local cluster

```bash
./scripts/bootstrap-kind.sh
```

### 2. Install Argo CD

```bash
./scripts/install-argocd.sh
```

### 3. Prepare the demo-api image

For the original local-only flow:

```bash
./scripts/build-load-demo-api-image.sh
```

For the GHCR-based flow, publish an image through GitHub Actions and then update the Helm image tag:

```bash
IMAGE_TAG="sha-<short-commit>" ./scripts/set-demo-api-image.sh
```

### 4. Deploy the root application

Use your real GitHub repository URL:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

### 5. Validate the baseline

```bash
./scripts/validate.sh
```

## Local Access

The demo API is exposed through ingress using the host:

```text
demo-api.local
```

Add it to `/etc/hosts` if needed:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
```

Then test:

```bash
curl http://demo-api.local/health
curl http://demo-api.local/ready
curl http://demo-api.local/version
curl http://demo-api.local/metrics
```

You can also test without editing `/etc/hosts`:

```bash
curl -H "Host: demo-api.local" http://localhost/health
```

## Validation

Run:

```bash
./scripts/validate.sh
```

The script validates the local GitOps baseline, demo-api workload, ingress path, Rollout state, and Prometheus checks.

To skip Prometheus HTTP checks:

```bash
SKIP_PROMETHEUS_HTTP=true ./scripts/validate.sh
```

Useful rollout checks:

```bash
./scripts/rollout-status.sh
./scripts/rollout-watch.sh
./scripts/check-rollout-analysis.sh
./scripts/show-rollout-capacity.sh
```

## Canary Release Workflow

After updating the demo-api image tag, Argo Rollouts creates a new ReplicaSet and routes canary traffic through ingress-nginx.

Typical commands:

```bash
kubectl argo rollouts get rollout demo-api -n startup-apps --watch
kubectl argo rollouts promote demo-api -n startup-apps
kubectl argo rollouts abort demo-api -n startup-apps
```

The current canary analysis checks whether Prometheus can scrape the canary service:

```promql
sum(up{job="demo-api-canary"})
```

This is a lightweight canary health gate. Real error-rate or latency-based analysis should be added after the demo-api exposes richer HTTP metrics.
