# Ingress Access

This document describes how local ingress access works in the v0.1 local GitOps baseline.

## Overview

The local baseline uses `ingress-nginx` to expose the `demo-api` service through Kubernetes Ingress.

The intended access path is:

```text
Client
  -> localhost:80 on the host VM
  -> kind control-plane port mapping
  -> ingress-nginx controller
  -> demo-api Service
  -> demo-api Pod
```

The default local hostname is:

```text
demo-api.local
```

## Prerequisites

The kind control-plane container must expose ports 80 and 443 to the host.

Check this with:

```bash
docker ps | grep startup-devops-baseline-control-plane
```

Expected port mapping:

```text
0.0.0.0:80->80/tcp
0.0.0.0:443->443/tcp
```

## GitOps Flow

The root Argo CD application manages platform applications under:

```text
clusters/local/platform/
```

The ingress controller is declared as:

```text
clusters/local/platform/ingress-nginx.yaml
```

After this file is committed and pushed to the Git repository, Argo CD should create and sync the `ingress-nginx` application automatically through the root application.

You can force Argo CD to refresh the root application during local testing:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

## Validate Applications

Check Argo CD applications:

```bash
kubectl get applications -n argocd
```

Expected applications:

```text
startup-devops-root
ingress-nginx
demo-api
```

The application name should be `ingress-nginx`. If you see a typo in your local output, check the manifest names first.

## Validate Controller

Check ingress-nginx pods:

```bash
kubectl get pods -n ingress-nginx
```

Check controller rollout:

```bash
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller
```

## Validate Demo API Ingress

Check the Ingress resource:

```bash
kubectl get ingress -n startup-apps
```

Test with an explicit Host header:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

Alternatively, add a local hosts entry:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
```

Then test:

```bash
curl http://demo-api.local/health
curl http://demo-api.local/ready
curl http://demo-api.local/version
```

## Helper Script

You can run:

```bash
./scripts/check-ingress.sh
```

The script checks the ingress controller rollout, the demo-api Ingress resource, and the demo-api HTTP endpoints through ingress.

## Troubleshooting

If the ingress controller application is not created, refresh the root application:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

If the ingress controller pod is pending, check node scheduling and hostPort conflicts:

```bash
kubectl describe pod -n ingress-nginx -l app.kubernetes.io/component=controller
```

If `curl http://demo-api.local/health` does not work, first test with the explicit Host header:

```bash
curl -H "Host: demo-api.local" http://localhost/health
```

If the Host header test works but the hostname test fails, the issue is local DNS or `/etc/hosts`, not Kubernetes ingress.

If port 80 is already used on the host VM, the kind control-plane container may fail to bind port 80. Stop the conflicting service or recreate the kind cluster with different port mappings.
