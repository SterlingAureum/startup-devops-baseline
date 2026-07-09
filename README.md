# startup-devops-baseline

A local-first DevOps and GitOps baseline for early-stage teams.

This repository demonstrates a small but practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, a demo FastAPI service, Prometheus, and validation scripts.

The current version focuses on a reproducible local environment. It is intentionally not a full production platform, but it follows a structure that can later evolve toward AWS EKS, Terraform, Karpenter, CloudNativePG, CI/CD, AI infrastructure workloads, and AIOps workflows.

## Current Version

```text
v0.1-local-gitops-baseline
```

Current capabilities:

- Local Kubernetes cluster with kind.
- Argo CD GitOps control plane.
- App-of-apps root application.
- demo-api deployed through Helm.
- ingress-nginx managed by Argo CD.
- Local ingress access through `demo-api.local`.
- Basic Prometheus monitoring.
- One-command validation with `scripts/validate.sh`.

## Architecture

```text
GitHub Repository
   |
   | watched by Argo CD
   v
startup-devops-root Application
   |
   +-- ingress-nginx Application
   +-- demo-api Application
   +-- monitoring Application
          |
          v
Local kind Kubernetes Cluster
```

The root application is the GitOps entry point. It syncs platform-level Argo CD Applications from `clusters/local/platform/`.

## Repository Structure

```text
startup-devops-baseline/
├── apps/
│   └── demo-api/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── src/
│       └── helm/
├── ci/
├── clusters/
│   └── local/
│       ├── root-app.yaml
│       └── platform/
├── docs/
├── examples/
├── platform/
│   ├── argocd
│   ├── ingress-nginx
│   └── monitoring/
└── scripts/
```

## Quick Start

### 1. Create the local cluster

```bash
./scripts/bootstrap-kind.sh
```

### 2. Install Argo CD

```bash
./scripts/install-argocd.sh
```

### 3. Build and load the demo-api image into kind

```bash
./scripts/build-load-demo-api-image.sh
```

### 4. Deploy the root application

Use your real GitHub repository URL:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

### 5. Validate the baseline

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

The script automatically creates a temporary port-forward for Prometheus checks, so it does not rely on a fixed local `localhost:9090` port.

To skip Prometheus HTTP checks:

```bash
SKIP_PROMETHEUS_HTTP=true ./scripts/validate.sh
```

## What v0.1 Does Not Include

The current version does not include:

- CI/CD image build workflow.
- GitHub Actions deployment pipeline.
- Argo Rollouts.
- Grafana dashboards.
- Alertmanager.
- AWS EKS.
- Terraform/OpenTofu infrastructure.
- Karpenter autoscaling.
- CloudNativePG/Postgres.
- GPU workloads.
- vLLM or AI inference workloads.

These are planned as future extensions.

## Documentation

Start with:

- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/GITOPS_WORKFLOW.md`
- `docs/INGRESS.md`
- `docs/OBSERVABILITY.md`
- `docs/TROUBLESHOOTING.md`
- `docs/ROADMAP.md`

## Roadmap

The next planned phase is:

```text
v0.2-ci-security-baseline
```

Planned focus:

- GitHub Actions image build.
- Docker image tagging strategy.
- Helm linting.
- Basic image vulnerability scanning.
- CI validation before GitOps deployment.

