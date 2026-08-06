# CI Quality Gate and Image Workflow

v0.7.0 introduced one reusable quality gate for both pull-request validation
and demo-api image publishing. v0.7.1 extended that contract to immutable image
identity. v0.7.2 consumes the verified identity as the only input to a
reviewable aws-dev promotion pull request. v0.7.3 retains the build origin in
Git and projects it into the live workload for end-to-end identity checks.
v0.7.4 reuses that reviewed identity to prepare history-based rollback PRs.
v0.9.1 moves the promoted identity into an isolated release values file while
the environment values remain immutable during promotion and rollback. v0.9.3
adds ordered, main-sourced aws-dev to aws-test and aws-test to aws-prod
Promotion PRs without rebuilding the image.

## Quality Gate

The local and GitHub Actions entry point is:

```bash
./scripts/validate-ci-quality-gates.sh
```

It performs:

1. Bash syntax validation for every script in `scripts/`.
2. Helm lint and template rendering with the default local values.
3. Static ownership validation for environment and release values.
4. Helm lint and template rendering for aws-dev, aws-test, and aws-prod with
   ordered environment and release files.
5. Digest-pinned rendering for the local Rollout and aws-dev Deployment.
6. Structured image identity metadata validation.
7. Metadata-driven aws-dev release promotion and source-mismatch rejection.
8. Ordered environment-promotion edge, immutable identity, stale-source,
   workflow-permission, and release-only diff validation.
9. Demo-api unit tests in the Dockerfile `test` stage.
10. A final build of the production runtime image.
11. Historical rollback restoration, idempotency, diff isolation, and invalid
   target rejection.

The unit tests do not require AWS, Kubernetes, or a live PostgreSQL cluster.
Database success and failure behavior is isolated with mocks, and tests never
print or load a real database credential.

## Reusable Workflow

`.github/workflows/reusable-quality-gates.yaml` owns the GitHub Actions
implementation.

It is called by:

- `.github/workflows/validate.yaml` for pull requests, pushes to `main`, and
  manual validation;
- `.github/workflows/demo-api-image-publish.yaml` before any image is pushed to
  GHCR.

The publish workflow has an explicit dependency:

```text
quality-gates
  -> build-and-push
  -> promote-aws-dev
```

If any shell, Helm, test, or runtime-image build check fails, the GHCR publish
job does not start.

After a successful build, the publishing job captures the digest output,
uploads structured identity metadata, and attaches signed build provenance to
the GHCR image. For a `main` push, the promotion job downloads that exact
artifact, validates its source and digest contract, creates a release branch,
and opens or reuses a pull request that changes only
`apps/demo-api/helm/values/releases/aws-dev.yaml`.

That release change contains:

```text
image repository
readable SHA tag
immutable image digest
application version
source repository
full source commit
workflow run ID
```

## Container Test Boundary

The demo-api Dockerfile has three stages:

```text
base
├── test
└── runtime
```

The `test` stage adds the test suite and executes it. The final `runtime` stage
inherits only the installed dependencies and application source from `base`;
the test files are not included in the deployed image.

## Promotion Boundary

v0.7.2 automates preparation, not approval:

- the build artifact is the promotion input;
- GitHub Actions creates `release/demo-api-sha-*`;
- the PR updates only aws-dev image and delivery identity;
- the aws-dev environment values file is unchanged;
- a human still reviews and merges;
- Argo CD reconciles Git after approval;
- GitHub Actions does not connect directly to EKS.

Promotion commits are excluded from image-publish path filters. Merging a
values-only promotion therefore cannot start another image build and cannot
form a publish/promotion loop.

## Ordered Environment Promotion

`.github/workflows/demo-api-promote-environment.yaml` is manual-only and must
be dispatched from `main`. The complete allowed chain is:

```text
build -> aws-dev       demo-api-image-publish.yaml
aws-dev -> aws-test    demo-api-promote-environment.yaml
aws-test -> aws-prod   demo-api-promote-environment.yaml
```

The environment workflow captures the source release from `origin/main`,
validates its exact release schema, verifies that the digest-addressed GHCR
manifest exists, and copies all image and build identity fields without
mutation. It renders the target Helm profile and permits exactly one changed
path: `values/releases/<target>.yaml`.

Each target has an independent concurrency group. If `main` moves between
capture, artifact verification, branch push, and PR creation, the workflow
fails closed and must be rerun. This deliberately conservative guard prevents
a PR from being created from a source release that is no longer current.

The workflow rejects skipped, reverse, same-environment, and build-to-later-
environment edges. It can create a PR but cannot merge it and has no AWS,
Kubernetes, EKS, or Argo CD credentials. v0.9.4 adds source-environment
validation evidence and environment-scoped rollback governance on top of this
ordered transport contract.

## Rollback Boundary

`.github/workflows/demo-api-rollback.yaml` is manual-only. It accepts a full
historical desired-state commit, verifies that it is an eligible release-only
commit contained in the selected base branch, restores the historical
`values/releases/aws-dev.yaml`, and opens a pull request.

The rollback job has only:

```text
contents: write
pull-requests: write
```

It has no AWS, package-registry, Kubernetes, or Argo CD permission. It cannot
merge the PR. The selected historical state is still subject to normal review,
and Argo CD acts only after the PR reaches the tracked branch.

The repository must allow GitHub Actions to create pull requests under
**Settings → Actions → General → Workflow permissions**. A manual feature
branch test can set `create_promotion_pr=true` and use that same feature branch
as `promotion_base_branch`.

GitHub-hosted runners already satisfy the Node.js 24 Action runtime
requirement. Self-hosted runners must be at least `2.327.1`.
