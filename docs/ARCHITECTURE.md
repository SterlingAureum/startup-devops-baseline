# Architecture

This document describes the current architecture of the startup-devops-baseline repository.

The current implementation focuses on the minimum kind + Argo CD loop. The goal is to build a local GitOps control-plane baseline before adding application workloads, ingress, monitoring, CI/CD, and cloud infrastructure.

## Current Architecture

```text
Developer
   |
   | update GitOps manifests
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

## Components

## 1. kind Cluster

kind provides a local Kubernetes cluster for development and validation.

The cluster is created by:

```bash
./scripts/bootstrap-kind.sh
```

The cluster name is:

```text
startup-devops-baseline
```

The kind configuration includes local port mappings for future ingress support:

```text
host port 80  -> container port 80
host port 443 -> container port 443
```

These mappings are prepared now, even though ingress-nginx is not installed until a later batch.

## 2. Argo CD

Argo CD is installed into the `argocd` namespace.

Installation script:

```bash
./scripts/install-argocd.sh
```

The script installs Argo CD using the upstream install manifest and waits for the main Argo CD deployments to become available.

## 3. Root Application

The repository uses an app-of-apps style entrypoint.

Root application manifest:

```text
clusters/local/root-app.yaml
```

The root application points to:

```text
clusters/local/platform
```

This directory will later contain Argo CD `Application` manifests for platform components such as:

- ingress-nginx
- monitoring
- demo-api

## 4. GitOps Flow

The intended GitOps flow is:

```text
1. Update manifests in Git.
2. Push changes to the remote repository.
3. Argo CD detects the change.
4. Argo CD syncs the desired state into Kubernetes.
5. Operators inspect status using kubectl or Argo CD UI.
```

The current root application is deployed by:

```bash
./scripts/deploy-root-app.sh
```

For real sync behavior, the repository must be pushed to a remote Git repository and `REPO_URL` must be provided.

Example:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

## Future Architecture Direction

The local architecture is designed to evolve toward the following structure:

```text
Git Repository
   |
   +-- platform components
   |     +-- ingress-nginx
   |     +-- monitoring
   |     +-- database operators
   |
   +-- application workloads
   |     +-- demo-api
   |     +-- future AI workloads
   |
   +-- cluster definitions
         +-- local
         +-- aws-eks
```

The long-term direction is:

```text
local GitOps baseline
-> CI/image workflow
-> progressive delivery
-> AWS EKS baseline
-> Karpenter autoscaling
-> CloudNativePG data baseline
-> AI infrastructure workload
-> AIOps extension
```
