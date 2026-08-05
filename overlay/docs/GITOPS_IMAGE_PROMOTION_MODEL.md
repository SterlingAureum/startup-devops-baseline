# GitOps Image Promotion Model

## Current model

This repository uses a single-repository, review-gated GitOps image promotion
model.

There are two different commits in a normal image release:

```text
commit A:
  changes source code or triggers image publishing
  GitHub Actions builds and pushes:
  ghcr.io/sterlingaureum/startup-devops-baseline/demo-api:sha-A
  and records digest sha256:D

commit B:
  is prepared on release/demo-api-sha-A by GitHub Actions
  updates apps/demo-api/helm/values/releases/aws-dev.yaml
  image.tag = sha-A
  image.digest = sha256:D
  is reviewed and merged through a pull request
  Argo CD syncs commit B
  the aws-dev Deployment rolls out image repository@sha256:D
```

This is expected.

A rollback creates a third desired-state commit:

```text
commit C:
  is prepared from a selected historical values-only release
  restores its complete image and delivery identity
  changes only apps/demo-api/helm/values/releases/aws-dev.yaml
  is reviewed and merged through a pull request
  is reconciled by Argo CD after approval
```

Commit C references the existing immutable digest. It does not rebuild or
retag the old artifact.

`commit B` is a release promotion commit. It promotes an already-published
image into aws-dev after human review.

## Why the image tag may not match the values commit

If `values/releases/aws-dev.yaml` is updated in commit B, the image tag and digest
inside that commit usually identify the artifact produced from commit A.

This is not a bug.

It is a consequence of separating:

```text
artifact build
```

from:

```text
environment promotion
```

## Delivery responsibilities

```text
CI:
  validate source and build the immutable artifact

Git:
  retain reviewed environment desired state

Argo CD:
  reconcile approved desired state

Human reviewer:
  approve or reject environment promotion
```

## Production alternatives

### Separate app and GitOps repositories

```text
app repo:
  source commit A
  image sha-A / sha256:D

gitops repo:
  release commit B
  image.tag = sha-A
  image.digest = sha256:D
```

This is a common production model.

### Implemented: CI-generated release commit

```text
commit A
  -> build image sha-A
  -> CI updates values/releases/aws-dev.yaml
  -> CI creates release commit B
```

This is the v0.7.2 model. CI creates the branch and pull request but does not
merge it.

The environment file is a separate ownership boundary. Build and rollback
automation must not modify `values/environments/aws-dev.yaml`; future
environment promotion copies only the release identity into the target release
file.

### Argo CD Image Updater

```text
GitHub Actions pushes image sha-A
Argo CD Image Updater detects the image
It updates GitOps manifests or Application parameters
Argo CD syncs the new desired state
```

This is more automated but adds another component.

## Implemented rollback model

Keep promotion review-gated. Do not add Argo CD Image Updater in v0.7 and do
not grant the image or rollback workflow direct EKS access. v0.7.4 completes
the model by creating a values-only Rollback PR from a validated historical
desired state, then applying the same Argo CD and runtime trace contract after
human approval.
