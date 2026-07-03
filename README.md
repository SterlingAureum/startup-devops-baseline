# startup-devops-baseline

A production-like DevOps and GitOps baseline for early-stage teams.

This repository demonstrates how to build a small but practical Kubernetes delivery baseline using local infrastructure first. The initial version focuses on a reproducible local Kubernetes environment with GitOps deployment, ingress, a demo API service, basic observability, validation scripts, and operational documentation.

The long-term goal is to evolve this baseline from a local GitOps demo into a cloud-ready startup platform blueprint that can later extend to AWS EKS, Terraform, Karpenter, CloudNativePG, AI infrastructure workloads, and AIOps-style operations.

## Current Version

```text
startup-devops-baseline v0.1
= kind
+ Argo CD
+ app-of-apps root application
+ local GitOps entrypoint
```

It does not deploy the demo API yet. The demo API, ingress, Helm chart, monitoring, and validation script will be added in later batches.

## Goals

- Bootstrap a local Kubernetes cluster with kind.
- Install Argo CD into the local cluster.
- Create an Argo CD root application.
- Prepare the repository for an app-of-apps GitOps workflow.
- Keep the structure simple enough to run locally and extend later.

## Repository Structure

```text
startup-devops-baseline/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   ├── GITOPS_WORKFLOW.md
│   ├── OBSERVABILITY.md
│   ├── ROLLBACK.md
│   ├── TROUBLESHOOTING.md
│   └── ROADMAP.md
│
├── scripts/
│   ├── bootstrap-kind.sh
│   ├── install-argocd.sh
│   ├── deploy-root-app.sh
│   └── cleanup.sh
│
├── clusters/
│   └── local/
│       ├── root-app.yaml
│       ├── platform/
│       │   └── README.md
│       └── values/
│           └── .gitkeep
│
├── platform/
│   ├── argocd/
│   ├── ingress-nginx/
│   └── monitoring/
│
├── apps/
│   └── demo-api/
│       ├── src/
│       ├── helm/
│       │   └── templates/
│       └── README.md
│
├── ci/
│   └── github-actions/
└── examples/
```

## Architecture

```text
Developer
   |
   | update manifests
   v
Git Repository
   |
   | watched by Argo CD
   v
Argo CD
   |
   | sync desired state
   v
Local kind Cluster
```

## Quick Start

Prerequisites:

- Docker
- kubectl
- kind

From the repository root:

```bash
chmod +x scripts/*.sh

./scripts/bootstrap-kind.sh
./scripts/install-argocd.sh
./scripts/deploy-root-app.sh
```

Check the cluster:

```bash
kubectl get nodes
kubectl get pods -n argocd
kubectl get applications -n argocd
```

Port-forward the Argo CD UI:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

Open:

```text
https://localhost:8080
```

Get the initial admin password:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Username:

```text
admin
```

## GitOps Repository URL

The default `clusters/local/root-app.yaml` uses a placeholder repository URL:

```text
https://github.com/YOUR_GITHUB_USERNAME/startup-devops-baseline.git
```

After pushing this repository to GitHub, run:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

If `REPO_URL` is not provided, the script applies the placeholder manifest. That is enough to create the root app object, but Argo CD will not be able to sync until the repository URL is corrected.

## Current Scope

Included in this batch:

- kind bootstrap script.
- Argo CD install script.
- Argo CD root application manifest.
- root app deployment script.
- cleanup script.
- deployment documentation.

Not included yet:

- demo API.
- Helm chart.
- ingress-nginx installation.
- monitoring stack.
- validate.sh.
- CI workflow.
- AWS EKS.
- Terraform.
- Karpenter.
- CloudNativePG.

## Next Step

The next batch should add the demo API service and Dockerfile. After that, the demo API can be deployed through Helm and connected to Argo CD.
