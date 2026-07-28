# CI Quality Gate and Image Workflow

v0.7.0 introduces one reusable quality gate for both pull-request validation
and demo-api image publishing.

## Quality Gate

The local and GitHub Actions entry point is:

```bash
./scripts/validate-ci-quality-gates.sh
```

It performs:

1. Bash syntax validation for every script in `scripts/`.
2. Helm lint and template rendering with the default local values.
3. Helm lint and template rendering with `values-aws-dev.yaml`.
4. Demo-api unit tests in the Dockerfile `test` stage.
5. A final build of the production runtime image.

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
```

If any shell, Helm, test, or runtime-image build check fails, the GHCR publish
job does not start.

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

## Current Boundary

v0.7.0 establishes quality gates only. It does not yet:

- deploy by image digest;
- generate build attestations;
- create GitOps promotion pull requests;
- update Helm values automatically;
- connect GitHub Actions directly to the EKS cluster;
- bypass human review before environment promotion.

Those delivery-chain capabilities are introduced incrementally in later v0.7
releases.
