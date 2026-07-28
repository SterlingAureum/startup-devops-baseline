# GHCR Image Workflow

The repository publishes demo-api images to GitHub Container Registry through
`.github/workflows/demo-api-image-publish.yaml`.

## Delivery Identity

Each successful build has two complementary identifiers:

```text
sha-<short-commit>
sha256:<64-character-digest>
```

The SHA tag is readable and maps the artifact to its source commit. The digest
is the immutable OCI content identity used by Kubernetes.

GitOps values retain both:

```yaml
image:
  repository: ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
  tag: "sha-<short-commit>"
  digest: "sha256:<64-character-digest>"
  pullPolicy: IfNotPresent
```

The Helm chart renders:

```text
ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@sha256:<digest>
```

`env.APP_VERSION` continues to use the SHA tag so `/version` remains easy to
read.

## Publishing

The workflow runs for:

- pushes to `main` that change demo-api source, tests, image-build inputs, or
  the image workflow;
- version tags matching `v*`;
- manual `workflow_dispatch`.

Helm values-only changes do not publish an image. This prevents a merged
promotion PR from recursively creating another image and promotion PR.

The publish job starts only after the reusable v0.7.0 quality gates pass. It
then:

1. builds and pushes the image;
2. captures the digest returned by `docker/build-push-action`;
3. writes `demo-api-image-metadata.json`;
4. uploads that metadata as a 30-day workflow artifact;
5. creates GitHub build-provenance attestation for the GHCR digest;
6. prints the tag, digest, and source commit in the workflow summary.

The build job requires:

```yaml
permissions:
  contents: read
  packages: write
  id-token: write
  attestations: write
  artifact-metadata: write
```

No custom registry token is stored. GHCR publishing and attestation use the
workflow's short-lived `GITHUB_TOKEN` and OIDC identity.

The promotion job separately requests:

```yaml
permissions:
  actions: read
  contents: write
  pull-requests: write
```

Those permissions can create the release branch and PR but do not approve or
merge it.

## Image Metadata

The uploaded JSON artifact records:

```text
schema version
image repository
SHA tag
OCI digest
digest-pinned image reference
source repository
full source commit
workflow run ID
```

This artifact is intentionally machine-readable. The v0.7.2 promotion job
consumes the exact build output without scraping console logs.

## Verify a Published Image

Copy the SHA tag and digest from the successful workflow summary, then run:

```bash
IMAGE_TAG="sha-<short-commit>" \
IMAGE_DIGEST="sha256:<64-character-digest>" \
./scripts/check-ghcr-demo-api-image.sh
```

The script verifies that the tag resolves to the expected digest and that the
digest-pinned manifest exists.

For a public repository, GitHub CLI can also verify build provenance:

```bash
gh attestation verify \
  "oci://ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@sha256:<digest>" \
  --repo SterlingAureum/startup-devops-baseline
```

GitHub artifact attestations are available for public repositories on current
plans. Private and internal repositories require an eligible GitHub Enterprise
Cloud plan.

## GitOps Promotion Pull Request

For a successful `main` push, the workflow:

1. downloads the metadata from the completed build job;
2. verifies the metadata repository and source commit against the workflow;
3. updates `values-aws-dev.yaml` by tag and digest;
4. validates the promoted Helm rendering;
5. creates or reuses `release/demo-api-sha-<short-commit>`;
6. creates or reuses a pull request into `main`.

The workflow never merges the pull request. Review and merge are the explicit
aws-dev promotion decision, after which Argo CD reconciles the approved Git
state.

To validate the PR flow before merging a feature branch, manually dispatch
the workflow from that feature branch with:

```text
create_promotion_pr = true
promotion_base_branch = feature/v0.7-cicd-gitops-promotion
```

The published commit must be contained in the selected base branch.

## Local Image Fallback

To return to a tag-only image loaded directly into kind:

```bash
IMAGE_TAG=0.1.1 ./scripts/set-demo-api-local-image.sh
```

This clears `image.digest`, restores `imagePullPolicy: Never`, and renders the
local `repository:tag` reference.

## Current Boundary

v0.7.2 creates the promotion branch and PR but does not approve or merge it,
connect GitHub Actions directly to EKS, or replace Argo CD as the deployment
controller. End-to-end desired-state and runtime identity correlation follows
in v0.7.3.
