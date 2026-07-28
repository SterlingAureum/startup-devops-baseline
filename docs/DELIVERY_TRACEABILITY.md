# Delivery Traceability

## Purpose

The delivery trace proves that the source selected by CI is the same artifact
reviewed in Git and the same image running in aws-dev.

```text
source commit
  -> SHA image tag and OCI digest
  -> image-build workflow run
  -> values-only promotion commit
  -> Argo CD synced revision
  -> Deployment and Pod annotations
  -> Pod imageID
  -> demo-api /version
```

This is a read-only operational check. It does not change Git, approve a
Promotion PR, trigger Argo CD, restart a workload, or call a database endpoint.

## Stored Git Identity

A metadata-driven Promotion PR writes the following fields to
`values-aws-dev.yaml`:

```yaml
image:
  repository: ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
  tag: "sha-<short-source-commit>"
  digest: "sha256:<immutable-content-digest>"

delivery:
  sourceRepository: "SterlingAureum/startup-devops-baseline"
  sourceCommit: "<full-source-commit>"
  workflowRunId: "<image-build-run-id>"

env:
  APP_VERSION: "sha-<short-source-commit>"
```

The PR still changes only this values file.

## Live Workload Identity

Helm renders the identity on both the workload and Pod template:

```text
platform.startup.dev/image-tag
platform.startup.dev/image-digest
platform.startup.dev/application-version
platform.startup.dev/source-repository
platform.startup.dev/source-commit
platform.startup.dev/workflow-run-id
```

Kubernetes continues to pull by `repository@sha256:digest`. The readable SHA
tag is retained for operators and `/version`.

## Validation

Run from a repository checkout containing the promotion commit that Argo CD is
expected to have synced:

```bash
git switch main
git pull --ff-only
./scripts/validate-demo-api-delivery-trace.sh
```

The script configures kubeconfig for the existing development EKS cluster and
requires:

```text
aws
git
jq
kubectl
python3
```

Useful overrides:

```bash
PROMOTION_REVISION=<full-promotion-commit> \
CONFIGURE_KUBECONFIG=false \
./scripts/validate-demo-api-delivery-trace.sh
```

`PROMOTION_REVISION` defaults to `HEAD`. The resolved commit must change only
`apps/demo-api/helm/values-aws-dev.yaml`, and Argo CD must report that exact
full commit as its synced revision.

The check then verifies:

1. the SHA tag matches the first seven characters of the full source commit;
2. the digest is a valid immutable `sha256` identity;
3. `APP_VERSION` matches the readable image tag;
4. the promotion commit changes only the aws-dev values file;
5. Argo CD is `Synced` and `Healthy` at the promotion commit;
6. Deployment and Pod annotations match Git;
7. the Deployment and every Pod use the digest-pinned image;
8. every container runtime `imageID` ends with the expected digest;
9. every demo-api Pod reports the expected version and `aws-dev` environment.

## Feature-Branch Boundary

While v0.7 is still developed on
`feature/v0.7-cicd-gitops-promotion`, use the reusable quality gate and a
feature-targeted Promotion PR to validate metadata insertion and Helm
rendering. Do not expect the live trace script to pass until the metadata-aware
promotion commit is on the branch tracked by the aws-dev Argo CD Application,
which is currently `main`.

The final v0.7 end-to-end validation uses this script after the main-branch
promotion and Argo CD reconciliation.
