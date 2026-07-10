# Argo Rollouts Troubleshooting

This document records common troubleshooting notes for the v0.3 Progressive Delivery baseline.

## Argo Rollouts Helm chart fetch fails with EOF

When syncing the `argo-rollouts` Application, Argo CD may temporarily fail with an error similar to:

```text
Failed to load target state: failed to generate manifest for source 1 of 1:
rpc error: code = Unknown desc = error fetching chart:
failed to fetch chart:
failed running helm:
helm pull --destination ... --version ... --repo https://argoproj.github.io/argo-helm argo-rollouts
failed exit status 1:
Error: looks like "https://argoproj.github.io/argo-helm" is not a valid chart repository or cannot be reached:
Get "https://argoproj.github.io/argo-helm/index.yaml": EOF
```

This usually means the Argo CD repo-server failed to reach the external Helm repository due to a transient network issue.

In local kind environments, this can happen because Argo CD pulls the Helm chart from an external GitHub Pages-backed Helm repository during sync.

Recommended actions:

1. Wait for a short period and retry sync.
2. Hard refresh the `argo-rollouts` Application:

```bash
kubectl -n argocd annotate application argo-rollouts \
  argocd.argoproj.io/refresh=hard --overwrite
```

3. Or hard refresh the root Application:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

4. If the error persists, check repo-server network access:

```bash
kubectl -n argocd exec deploy/argocd-repo-server -- \
  sh -c 'wget -S -O- https://argoproj.github.io/argo-helm/index.yaml | head'
```

If the command fails inside the repo-server Pod but works on the host machine, the issue is likely related to in-cluster network access, DNS, proxy, or temporary upstream connectivity.

## Production note

For a more stable production baseline, consider vendoring critical platform manifests into the repository instead of relying on live external Helm repository fetches during every sync.

For example, a future version may move from this pattern:

```text
Argo CD Application
  -> external Helm repository
  -> argo-rollouts chart
```

to this pattern:

```text
Argo CD Application
  -> this Git repository
  -> vendored platform manifests
```

This improves reproducibility and reduces dependency on external network availability during GitOps sync.
