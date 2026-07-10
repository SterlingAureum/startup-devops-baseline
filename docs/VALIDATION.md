# Validation Guide

## Local Validation

Run before pushing changes:

```bash
helm lint apps/demo-api/helm
helm template demo-api apps/demo-api/helm

docker build -t demo-api-test apps/demo-api
```

## CI Validation

GitHub Actions validates:

- Helm chart syntax
- Helm template rendering
- Docker image build
- Dockerfile quality checks

CI validates changes but does not deploy workloads.

## GitOps Validation

After Argo CD synchronization:

```bash
kubectl get application -n argocd
./scripts/validate.sh
```

Expected state:

- Root Application: Synced / Healthy
- demo-api Application: Synced / Healthy
- ingress-nginx Application: Synced / Healthy
- monitoring Application: Synced / Healthy
