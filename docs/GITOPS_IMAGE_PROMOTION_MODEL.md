# GitOps Image Promotion Model

## Current model

This repository currently uses a single-repository, semi-automated GitOps image promotion model.

There are two different commits in a normal image release:

```text
commit A:
  changes source code or triggers image publishing
  GitHub Actions builds and pushes:
  ghcr.io/sterlingaureum/startup-devops-baseline/demo-api:sha-A

commit B:
  updates apps/demo-api/helm/values.yaml
  image.tag = sha-A
  Argo CD syncs commit B
  Argo Rollouts deploys image sha-A
```

This is expected.

`commit B` is a release promotion commit. It promotes an already-published image into the local environment.

## Why the image tag may not match the values commit

If `values.yaml` is updated in commit B, the image tag inside that commit usually points to commit A.

This is not a bug.

It is a consequence of separating:

```text
artifact build
```

from:

```text
environment promotion
```

## Why this is acceptable for v0.3.2 / v0.3.3

The purpose of the current version is to demonstrate:

```text
- GitHub Actions can build and publish an immutable image
- GHCR can store the image
- Helm values explicitly declare the promoted image
- Argo CD syncs desired state from Git
- Argo Rollouts performs canary release
```

It is intentionally not fully automatic yet.

## Production alternatives

### Separate app and GitOps repositories

```text
app repo:
  source commit A
  image sha-A

gitops repo:
  release commit B
  image.tag = sha-A
```

This is a common production model.

### CI-generated release commit

```text
commit A
  -> build image sha-A
  -> CI updates values.yaml
  -> CI creates release commit B
```

This automates the current manual promotion step.

### Argo CD Image Updater

```text
GitHub Actions pushes image sha-A
Argo CD Image Updater detects the image
It updates GitOps manifests or Application parameters
Argo CD syncs the new desired state
```

This is more automated but adds another component.

## Current recommendation

Keep manual image promotion for v0.3.3.

Consider automated image promotion in a later version after the local progressive delivery baseline is complete.
