# Troubleshooting

This document lists common issues for the current kind + Argo CD baseline.

## kind cluster already exists

If the cluster already exists, `bootstrap-kind.sh` will skip creation.

Check clusters:

```bash
kind get clusters
```

Delete and recreate:

```bash
./scripts/cleanup.sh
./scripts/bootstrap-kind.sh
```

## kubectl is pointing to the wrong cluster

Set the context manually:

```bash
kubectl config use-context kind-startup-devops-baseline
```

Check nodes:

```bash
kubectl get nodes
```

## Argo CD pods are not ready

Check pod status:

```bash
kubectl get pods -n argocd
```

Describe a failing pod:

```bash
kubectl describe pod -n argocd <pod-name>
```

Check recent events:

```bash
kubectl get events -n argocd --sort-by=.lastTimestamp
```

## Argo CD UI is not accessible

Start port-forwarding:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

Open:

```text
https://localhost:8080
```

The browser may show a TLS warning because the local certificate is self-signed.

## Root app cannot sync

The default root app uses a placeholder repository URL.

Deploy again with a real Git repository URL:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

Then check:

```bash
kubectl describe application startup-devops-root -n argocd
```

## Argo CD admin password

Get the initial admin password:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```
