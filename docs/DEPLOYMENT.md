# Deployment Guide

This guide describes how to deploy the v0.1 local GitOps baseline from a clean local environment.

## Prerequisites

Required tools:

- Docker
- kind
- kubectl
- curl
- git
- helm, recommended for local Helm template checks

Verify tools:

```bash
docker version
kind version
kubectl version --client
helm version
curl --version
git --version
```

## 1. Create the kind Cluster

From the repository root:

```bash
./scripts/bootstrap-kind.sh
```

The kind cluster should expose local HTTP and HTTPS ports so ingress can be tested from the host.

Check:

```bash
kubectl get nodes
kubectl get pods -n kube-system
```

Expected state:

- Node is `Ready`.
- CoreDNS is Ready.
- kube-proxy is Ready.
- kindnet is Ready.

## 2. Install Argo CD

```bash
./scripts/install-argocd.sh
```

The script installs Argo CD into the `argocd` namespace using server-side apply. This avoids large CRD annotation issues in newer Argo CD manifests.

Check:

```bash
kubectl get pods -n argocd
kubectl get crd | grep argoproj
```

## 3. Build and Load demo-api Image

Since the v0.1 baseline runs locally with kind, the demo image is built locally and loaded into the kind cluster.

```bash
./scripts/build-load-demo-api-image.sh
```

Check that the image exists in the kind node if needed:

```bash
docker exec startup-devops-baseline-control-plane crictl images | grep demo-api
```

## 4. Push Repository Changes

Argo CD reads manifests and Helm charts from Git. Make sure your repository has been pushed to GitHub or another reachable Git server.

```bash
git status
git add .
git commit -m "chore: prepare v0.1 local gitops baseline"
git push
```

## 5. Deploy Root Application

Deploy the Argo CD root application with the real repository URL:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

The root app syncs the platform applications under:

```text
clusters/local/platform/
```

Expected applications:

```bash
kubectl get applications -n argocd
```

Expected result:

```text
startup-devops-root   Synced   Healthy
demo-api              Synced   Healthy
ingress-nginx         Synced   Healthy
monitoring            Synced   Healthy
```

## 6. Validate Workloads

Check demo-api:

```bash
kubectl get pods -n startup-apps
kubectl get deploy -n startup-apps
kubectl get svc -n startup-apps
kubectl get ingress -n startup-apps
```

Check ingress-nginx:

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

Check monitoring:

```bash
kubectl get pods -n monitoring
kubectl get svc -n monitoring
```

## 7. Test demo-api Through Ingress

Without editing `/etc/hosts`:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
curl -H "Host: demo-api.local" http://localhost/metrics
```

With `/etc/hosts`:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
curl http://demo-api.local/health
```

## 8. Run Full Validation

```bash
./scripts/validate.sh
```

The script validates:

- Kubernetes cluster access.
- kube-system core pods.
- Argo CD core components.
- Argo CD Application status.
- demo-api deployment and service.
- ingress-nginx deployment.
- demo-api ingress.
- demo-api HTTP endpoints.
- Prometheus deployment and query path.

## 9. Cleanup

To delete the local kind cluster:

```bash
./scripts/cleanup.sh
```

Or directly:

```bash
kind delete cluster --name startup-devops-baseline
```

## Notes

If Argo CD cannot sync the applications, confirm that:

- `REPO_URL` points to your real repository.
- The repository is public, or Argo CD has credentials to access it.
- The expected paths exist in the Git repository.
- Changes have been pushed to Git.
