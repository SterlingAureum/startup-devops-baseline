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

- pushes to `main` that change `apps/demo-api/**`;
- version tags matching `v*`;
- manual `workflow_dispatch`.

The publish job starts only after the reusable v0.7.0 quality gates pass. It
then:

1. builds and pushes the image;
2. captures the digest returned by `docker/build-push-action`;
3. writes `demo-api-image-metadata.json`;
4. uploads that metadata as a 30-day workflow artifact;
5. creates GitHub build-provenance attestation for the GHCR digest;
6. prints the tag, digest, and source commit in the workflow summary.

The workflow requires:

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

This artifact is intentionally machine-readable so v0.7.2 can consume the
exact build output without scraping console logs.

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

## Manual GitOps Promotion

v0.7.1 still uses an explicit release commit:

```bash
VALUES_FILE=apps/demo-api/helm/values-aws-dev.yaml \
IMAGE_TAG="sha-<short-commit>" \
IMAGE_DIGEST="sha256:<64-character-digest>" \
./scripts/set-demo-api-image.sh

git add apps/demo-api/helm/values-aws-dev.yaml
git commit -m "release: promote aws-dev demo-api sha-<short-commit>"
git push
```

For the local GitOps values, omit `VALUES_FILE`.

## Local Image Fallback

To return to a tag-only image loaded directly into kind:

```bash
IMAGE_TAG=0.1.1 ./scripts/set-demo-api-local-image.sh
```

This clears `image.digest`, restores `imagePullPolicy: Never`, and renders the
local `repository:tag` reference.

## Current Boundary

v0.7.1 records and verifies immutable artifact identity. It does not create a
promotion branch, modify Helm values automatically, merge changes, or connect
GitHub Actions directly to EKS. Reviewable promotion automation begins in
v0.7.2.
