# CI Quality Gate and Image Workflow

v0.7.0 introduced one reusable quality gate for both pull-request validation
and demo-api image publishing. v0.7.1 extended that contract to immutable image
identity. v0.7.2 consumes the verified identity as the only input to a
reviewable aws-dev promotion pull request. v0.7.3 retains the build origin in
Git and projects it into the live workload for end-to-end identity checks.

## Quality Gate

The local and GitHub Actions entry point is:

```bash
./scripts/validate-ci-quality-gates.sh
```

It performs:

1. Bash syntax validation for every script in `scripts/`.
2. Helm lint and template rendering with the default local values.
3. Helm lint and template rendering with `values-aws-dev.yaml`.
4. Digest-pinned rendering for the local Rollout and aws-dev Deployment.
5. Structured image identity metadata validation.
6. Metadata-driven aws-dev values promotion and source-mismatch rejection.
7. Demo-api unit tests in the Dockerfile `test` stage.
8. A final build of the production runtime image.

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
`apps/demo-api/helm/values-aws-dev.yaml`.

That values change contains:

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
- a human still reviews and merges;
- Argo CD reconciles Git after approval;
- GitHub Actions does not connect directly to EKS.

Promotion commits are excluded from image-publish path filters. Merging a
values-only promotion therefore cannot start another image build and cannot
form a publish/promotion loop.

The repository must allow GitHub Actions to create pull requests under
**Settings → Actions → General → Workflow permissions**. A manual feature
branch test can set `create_promotion_pr=true` and use that same feature branch
as `promotion_base_branch`.

GitHub-hosted runners already satisfy the Node.js 24 Action runtime
requirement. Self-hosted runners must be at least `2.327.1`.
