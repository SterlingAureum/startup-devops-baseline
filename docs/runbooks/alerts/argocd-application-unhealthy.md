# ArgoCDApplicationUnhealthy

## Meaning

At least one Argo CD Application stayed outside `Healthy` or `Progressing` for
10 minutes. Intentional `OutOfSync` alone is not selected by this alert unless
the Application health is also unhealthy.

## Impact

GitOps reconciliation may be blocked, degraded, or unable to establish the
declared platform or application state.

## First response

```bash
kubectl -n argocd get applications -o wide
kubectl -n argocd describe application <application-name>
kubectl -n argocd get application <application-name> -o yaml
```

Record sync status, health status, target revision, operation phase, conditions,
and the first unhealthy resource. Confirm whether the environment is in an
intentional feature-testing or restoration phase.

## Diagnosis and recovery

- Compare the exact Git revision with the live Application source and Helm
  parameters.
- Inspect the first failed child resource instead of repeatedly resyncing the
  Root Application.
- If an operation is already running, use the repository's serialized Argo CD
  operation helpers and bounded recovery procedure.
- Do not patch target revisions or parameters directly in production.
- Preserve the existing production approval and reviewed Git change boundary.

Resolve when the Application is Healthy, the intended revision is reconciled,
no operation error remains, and dependent application health checks pass.
