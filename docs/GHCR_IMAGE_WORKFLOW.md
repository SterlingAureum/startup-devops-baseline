# GHCR Image Workflow

v0.3.2 introduces a registry-based image workflow for `demo-api` using GitHub Container Registry (GHCR).

## Why this exists

Earlier local versions used this flow:

```text
docker build locally
  -> kind load docker-image
  -> imagePullPolicy: Never
  -> Argo CD sync
  -> Argo Rollouts canary
```

That is useful for local kind testing, but it is not close enough to a production release workflow.

v0.3.2 adds this flow:

```text
git push
  -> GitHub Actions
  -> docker build
  -> push image to GHCR
  -> manually update Helm image tag
  -> Argo CD sync
  -> Argo Rollouts canary
```

This version intentionally does not auto-commit image tags back to Git. Image promotion remains manual and auditable.

## Image repository

Default GHCR repository:

```text
ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
```

GitHub Actions derives the image name from the repository:

```text
ghcr.io/${{ github.repository }}/demo-api
```

For `SterlingAureum/startup-devops-baseline`, that becomes:

```text
ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
```

## Tags

The image publishing workflow creates tags such as:

```text
sha-<short-commit>
latest
v0.3.2
```

The preferred deployment tag is the immutable SHA tag:

```text
sha-82aa684
```

Avoid deploying `latest` through GitOps because it is mutable and makes rollback harder to reason about.

## Publishing image

The workflow runs on:

- pushes to `main` that change `apps/demo-api/**`
- version tags matching `v*`
- manual `workflow_dispatch`

Workflow file:

```text
.github/workflows/demo-api-image-publish.yaml
```

It requires:

```yaml
permissions:
  contents: read
  packages: write
```

No custom token is required for publishing to GHCR from the same repository; it uses `GITHUB_TOKEN`.

## GHCR visibility

For a local kind cluster to pull from GHCR without an image pull secret, the package must be public.

If the GHCR package is private, create an image pull secret and configure `imagePullSecrets` in Helm values.

## Switching demo-api to a GHCR image

After GitHub Actions publishes an image, update Helm values with:

```bash
IMAGE_TAG=sha-<short-commit> ./scripts/set-demo-api-image.sh
```

This updates:

```text
apps/demo-api/helm/values.yaml
```

Fields changed:

```yaml
image:
  repository: ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
  tag: "sha-<short-commit>"
  pullPolicy: IfNotPresent

env:
  APP_VERSION: "sha-<short-commit>"
```

Then commit and push:

```bash
git add apps/demo-api/helm/values.yaml
git commit -m "release: update demo-api image to sha-<short-commit>"
git push
```

Argo CD will sync the Helm values update and Argo Rollouts will perform the canary rollout.

## Local fallback

To switch back to the local kind image mode:

```bash
IMAGE_TAG=0.1.1 ./scripts/set-demo-api-local-image.sh
```

This restores:

```yaml
image:
  repository: startup-devops-baseline/demo-api
  pullPolicy: Never
```

Use local mode when testing without a registry.

## Current boundary

v0.3.2 does not include:

- automatic GitOps tag updates
- Argo CD Image Updater
- ECR integration
- EKS image pull secret / IAM integration

Those are future production-hardening topics.
