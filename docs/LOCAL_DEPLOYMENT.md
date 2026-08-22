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

For the GHCR-based flow, publish an image through GitHub Actions and then
update the Helm image identity:

```bash
IMAGE_TAG="sha-<short-commit>" \
IMAGE_DIGEST="sha256:<64-character-digest>" \
./scripts/set-demo-api-image.sh
```

### 4. Deploy the root application

#### Stable HEAD deployment after merge

Use your real GitHub repository URL:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

The stable default is `TARGET_REVISION=HEAD` with automated Root sync and
self-heal. The Root source preflight requires remote HEAD to contain
`clusters/local/platform/Chart.yaml` before Kubernetes is contacted. During a
platform source migration, do not use this path until the migration reaches
remote HEAD.

#### Feature-revision validation

Do not edit `clusters/local/root-app.yaml` or the child Application YAML to
commit a temporary feature name. Build and load the local image, push the
feature branch, and use the branch-aware workflow:

```bash
IMAGE_TAG=v0.11.3-local \
  ./scripts/build-load-demo-api-image.sh

TARGET_REVISION=feature/v0.11-observability-sre-baseline \
IMAGE_TAG=v0.11.3-local \
  ./scripts/deploy-local-feature-gitops.sh
```

The script resolves the pushed feature branch to one full commit SHA, requires
the local checkout to match it, and passes that SHA through the Root Helm
App-of-Apps to every same-repository child. The exact local-image allowlist is
also rendered by the Root. The Root remains manual but must be `Synced`; a Root
resync is safe because it no longer resets feature children to `HEAD`.

After manual Canary completion and validation, use the feature baseline while
the increment is still unmerged:

```bash
TARGET_REVISION=feature/v0.11-observability-sre-baseline \
  ./scripts/restore-local-feature-baseline.sh
```

After the platform Chart reaches remote HEAD, use
`./scripts/restore-local-gitops-head.sh` for the stable main baseline.

See `docs/V0.11.3_LOCAL_FEATURE_GITOPS_VALIDATION.md` for the state model and
acceptance commands, and
`docs/V0.11.3.5_PRE_MERGE_BASELINE_RESTORATION.md` for revision content
preflight and the pre-merge/post-merge restoration boundary.

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

After updating the demo-api image tag and digest, Argo Rollouts creates a new
ReplicaSet and routes canary traffic through ingress-nginx.

Typical commands:

```bash
kubectl argo rollouts get rollout demo-api -n startup-apps --watch
kubectl argo rollouts promote demo-api -n startup-apps
kubectl argo rollouts abort demo-api -n startup-apps
kubectl argo rollouts retry rollout demo-api -n startup-apps
```

The current canary analysis checks whether Prometheus can scrape the canary service:

```promql
sum(up{job="demo-api-canary"})
```

This is a lightweight canary health gate. Real error-rate or latency-based analysis should be added after the demo-api exposes richer HTTP metrics.
