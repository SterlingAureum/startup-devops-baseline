# Deployment

This document explains how to deploy the current v0.1 kind + Argo CD baseline.

The current batch only creates the local Kubernetes cluster, installs Argo CD, and creates the root GitOps application.

It does not deploy the demo API, ingress-nginx, or monitoring yet.

## Prerequisites

Install the following tools before running the scripts:

- Docker
- kubectl
- kind

Check versions:

```bash
docker version
kubectl version --client
kind version
```

## 1. Prepare Scripts

From the repository root:

```bash
chmod +x scripts/*.sh
```

## 2. Create the kind Cluster

```bash
./scripts/bootstrap-kind.sh
```

Expected checks:

```bash
kubectl get nodes
kubectl cluster-info --context kind-startup-devops-baseline
```

The cluster name is:

```text
startup-devops-baseline
```

## 3. Install Argo CD

```bash
./scripts/install-argocd.sh
```

Expected checks:

```bash
kubectl get pods -n argocd
kubectl get svc -n argocd
```

## 4. Deploy the Root Application

If the repository has not been pushed to GitHub yet, you can still apply the placeholder root app:

```bash
./scripts/deploy-root-app.sh
```

This creates the Argo CD application object, but sync will not work correctly until the repository URL points to a real Git repository.

After pushing the repository to GitHub, run:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

Check the application:

```bash
kubectl get applications -n argocd
kubectl describe application startup-devops-root -n argocd
```

## 5. Access Argo CD UI

Port-forward the Argo CD API server:

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

## 6. Cleanup

To delete the local kind cluster:

```bash
./scripts/cleanup.sh
```

This deletes the full local Kubernetes cluster.

## Current Limitation

The root application points to `clusters/local/platform`, but that directory does not deploy real platform components yet.

This is intentional for the current batch.

The next batches will add:

- demo API service
- Helm chart
- ingress-nginx
- monitoring
- validation script
