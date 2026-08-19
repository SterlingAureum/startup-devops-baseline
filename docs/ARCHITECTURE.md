# Local Kubernetes Architecture

This document describes the local GitOps architecture.

The repository now provides a complete local GitOps and progressive delivery baseline. It combines CI image publishing, Argo CD application reconciliation, Argo Rollouts canary delivery, ingress-nginx traffic routing, and Prometheus-based rollout analysis.

## Current Architecture

```text
Developer
   |
   | push application or GitOps changes
   v
GitHub Repository
   |
   +-- GitHub Actions validates Helm and builds demo-api
   +-- GHCR stores versioned demo-api images
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

## 1. Local Kubernetes Cluster

kind provides the local Kubernetes environment used for development and validation.

The cluster is created with:

```bash
./scripts/bootstrap-kind.sh
```

The cluster name is:

```text
startup-devops-baseline
```

The kind configuration maps host ports 80 and 443 to the ingress-ready control-plane node so `demo-api.local` can be reached from the workstation.

## 2. Argo CD Control Plane

Argo CD is installed in the `argocd` namespace:

```bash
./scripts/install-argocd.sh
```

The root Application is defined in:

```text
clusters/local/root-app.yaml
```

It watches:

```text
clusters/local/platform/
```

That directory contains child Application definitions for ingress-nginx, Argo Rollouts, monitoring, and demo-api.

## 3. Application Delivery

The demo API is packaged as a Helm chart under:

```text
apps/demo-api/helm/
```

The chart renders:

- a demo-api `Rollout`;
- stable and canary Services;
- an ingress-nginx Ingress;
- an Argo Rollouts `AnalysisTemplate`;
- supporting ServiceAccount and chart metadata.

The current release process uses readable commit-derived GHCR tags, immutable
OCI digests, build provenance, and reviewable GitOps promotion pull requests
that update the aws-dev Helm values without writing directly to `main`.

## 4. Progressive Delivery

Argo Rollouts manages the demo-api canary release.

The delivery flow is:

```text
new image tag and digest committed to Git
  -> Argo CD sync
  -> new ReplicaSet created
  -> ingress-nginx shifts canary traffic
  -> AnalysisRun queries Prometheus
  -> operator promotes or aborts
  -> stable revision updated or previous revision retained
```

The rollout strategy includes explicit `maxSurge` and `maxUnavailable` settings so temporary capacity growth is visible and controlled.

## 5. Traffic Routing

The local environment uses ingress-nginx for HTTP routing and canary traffic splitting.

The primary hostname is:

```text
demo-api.local
```

Stable and canary Services allow Argo Rollouts to direct traffic to separate ReplicaSets during a release.

## 6. Monitoring and Analysis

The active v0.11.1 metrics foundation is an Operator-managed
`kube-prometheus-stack` release in the `observability` Namespace. It provides
Prometheus, kube-state-metrics, and node-exporter with bounded local and AWS
profiles. The original `platform/monitoring/prometheus/` resources are retained
only as historical v0.1 material.

A compatibility ServiceMonitor scrapes the existing stable and canary
demo-api Services and preserves their Service names as Prometheus `job`
labels. The current AnalysisTemplate can therefore continue to verify the
canary target with its existing query. Error-rate, latency, and SLO-based
release gates remain v0.11.2 through v0.11.6 work.

## 7. CI and Image Publishing

GitHub Actions workflows are stored in:

```text
.github/workflows/
```

They provide:

- repository and Helm validation;
- demo-api container image build;
- GHCR image publication;
- commit-derived image tags;
- immutable digest identity and build provenance.

CI builds artifacts, while Git remains the source of truth for deployment state.

## 8. Scope

This document covers only the local kind environment. The AWS networking, EKS,
workload IAM, Karpenter, AWS FIS, and CloudNativePG operator architecture is
documented in `docs/AWS_EKS_ARCHITECTURE.md`.

The local environment remains the fast GitOps and progressive-delivery
validation path. The `aws-dev` environment is the cloud infrastructure,
capacity, application-delivery, and data-platform integration environment.
