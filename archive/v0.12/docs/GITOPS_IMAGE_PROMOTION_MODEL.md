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

After aws-dev, the same artifact can produce two additional desired-state
commits without another image build:

```text
commit D:
  reads values/releases/aws-dev.yaml from main
  copies its complete immutable identity to values/releases/aws-test.yaml
  is reviewed and merged through an aws-dev -> aws-test PR

commit E:
  reads values/releases/aws-test.yaml from main
  copies its complete immutable identity to values/releases/aws-prod.yaml
  is reviewed and merged through an aws-test -> aws-prod PR
```

The workflow rejects direct build to test/prod, dev to prod, reverse, and
same-environment transitions.

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

The environment file is a separate ownership boundary. Build, promotion, and
rollback automation must not modify `values/environments/aws-dev.yaml`;
environment promotion copies only the release identity into the target release
file.

### Implemented: ordered environment promotion

`.github/workflows/demo-api-promote-environment.yaml` implements the
post-build transitions. It always reads the source release from the current
`main`, validates its immutable digest and source identity, proves the exact
GHCR digest exists, and changes only the target release file.

The workflow uses an independent concurrency group for each target
environment. It records the captured main revision and rejects the operation
if main changes before the branch is pushed or before the PR is opened. This
prevents a workflow run from silently promoting an expired source snapshot.

GitHub Actions only prepares the branch and PR. It neither merges nor connects
to EKS. v0.9.4 requires a separate, reviewed source qualification evidence
record from `main` and enters the target GitHub Environment before preparing
the Promotion PR. The evidence must match the current source release and remain
within its freshness window. v0.9.5 additionally requires a reviewed, fresh
AWS runtime record for the source environment. The runtime record must match
the same release bytes and live digest identity; it is collected locally so
the Promotion workflow retains zero EKS access.

### Argo CD Image Updater

```text
GitHub Actions pushes image sha-A
Argo CD Image Updater detects the image
It updates GitOps manifests or Application parameters
Argo CD syncs the new desired state
```

This is more automated but adds another component.

## Implemented environment rollback model

Keep promotion review-gated. Do not add Argo CD Image Updater and do not grant
the image, environment-promotion, evidence, or rollback workflow direct EKS
access. v0.9.4 accepts aws-dev, aws-test, or aws-prod as the rollback target,
restores only a historical target-release-only commit, proves the old digest
still exists, enters the target GitHub Environment, and opens a CODEOWNERS-
protected PR. It never rewrites environment configuration or changes the
build-once identity model.
