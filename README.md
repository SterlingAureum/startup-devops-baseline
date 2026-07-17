# startup-devops-baseline

A local-first DevOps, GitOps, and progressive delivery baseline for early-stage teams.

This repository demonstrates a practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, Argo Rollouts, GHCR image publishing, Prometheus, and a small demo API service.

The current stage focuses on a reproducible local environment. It is intentionally not a full production platform yet, but the repository is structured to evolve toward AWS EKS, Terraform/OpenTofu, Karpenter, CloudNativePG, observability, security controls, AI infrastructure workloads, and AIOps workflows.

## Current Version

```text
v0.3.3-prometheus-canary-analysis
```

Current capabilities:

- Local Kubernetes cluster with kind.
- Argo CD GitOps control plane.
- App-of-apps root application.
- demo-api deployed through Helm.
- ingress-nginx managed by Argo CD.
- Argo Rollouts based progressive delivery.
- ingress-nginx based canary traffic routing.
- stable and canary services for demo-api.
- GHCR-based image publishing workflow.
- Manual GitOps image promotion through Helm values.
- Prometheus monitoring for stable and canary targets.
- Prometheus-based Argo Rollouts AnalysisTemplate / AnalysisRun.
- Manual promote / abort workflow for controlled releases.
- Rollout capacity guardrails with `maxSurge` and `maxUnavailable`.
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
   +-- argo-rollouts Application
   +-- monitoring Application
   +-- demo-api Application
          |
          +-- Rollout/demo-api
          +-- Service/demo-api-stable
          +-- Service/demo-api-canary
          +-- Ingress/demo-api
          +-- AnalysisTemplate/demo-api-canary-health
          v
Local kind Kubernetes Cluster
```

The root application is the GitOps entry point. It syncs platform-level Argo CD Applications from `clusters/local/platform/`.

Argo CD is responsible for synchronizing desired state from Git. Argo Rollouts is responsible for canary rollout behavior, traffic shifting, AnalysisRun execution, and promotion/abort workflows.

## Release Flow

The current release flow is intentionally semi-automated:

```text
code change or image trigger
  ↓
GitHub Actions builds demo-api image
  ↓
image is pushed to GHCR
  ↓
operator updates Helm image tag in values.yaml
  ↓
Argo CD syncs the demo-api Application
  ↓
Argo Rollouts starts canary rollout
  ↓
Prometheus AnalysisRun validates canary target health
  ↓
operator promotes or aborts
  ↓
new revision becomes stable
```

This version uses manual GitOps image promotion. In a single-repository baseline, the image build commit and the image promotion commit may be different. This is expected for the current version.

## Repository Structure

```text
startup-devops-baseline/
├── .github/
│   └── workflows/
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
│   ├── argocd/
│   ├── argo-rollouts/
│   ├── ingress-nginx/
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

## Version History

| Version | Status | Focus |
|---|---:|---|
| v0.1 | Completed | Local kind + Argo CD GitOps baseline |
| v0.2 | Completed | GitHub Actions CI validation and image build checks |
| v0.3 | Completed | Argo Rollouts progressive delivery |
| v0.3.1 | Completed | ingress-nginx canary traffic routing |
| v0.3.2 | Completed | GHCR image publishing and manual GitOps image promotion |
| v0.3.3 | Completed | Prometheus-based canary analysis and rollout capacity notes |

## What This Repository Is

This repository is a learning and portfolio baseline for:

- DevOps platform structure.
- GitOps with Argo CD.
- Helm-based app delivery.
- Progressive delivery with Argo Rollouts.
- Ingress-based canary routing.
- Registry-based image publishing.
- Prometheus-based rollout analysis.
- Local-first iteration before moving to cloud infrastructure.

## What This Repository Is Not Yet

The current version does not yet include:

- Fully automated image tag promotion.
- Argo CD Image Updater.
- Separate app and GitOps repositories.
- AWS EKS.
- Terraform/OpenTofu infrastructure.
- AWS Load Balancer Controller.
- AWS ECR.
- Karpenter autoscaling.
- CloudNativePG/Postgres.
- Grafana dashboards.
- Alertmanager.
- Production-grade security policy.
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
- `docs/GHCR_IMAGE_WORKFLOW.md`
- `docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md`
- `docs/CANARY_CAPACITY_AND_COST.md`
- `docs/GITOPS_IMAGE_PROMOTION_MODEL.md`
- `docs/TROUBLESHOOTING.md`
- `docs/ROADMAP.md`

## Roadmap

The next major planned phase is:

```text
v0.4-aws-eks-baseline
```

Planned focus:

- Terraform/OpenTofu based AWS infrastructure.
- VPC and EKS baseline.
- Managed node groups.
- Argo CD bootstrap on EKS.
- ingress exposure through AWS-native components.
- GHCR or ECR image pull strategy.
- Reusing the current demo-api GitOps and Rollouts flow on EKS.

Later phases may include:

- Karpenter autoscaling.
- CloudNativePG/Postgres baseline.
- production observability stack.
- policy and security controls.
- AI infrastructure extension.
- AIOps-oriented operational workflows.
