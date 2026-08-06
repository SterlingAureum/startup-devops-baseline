# demo-api Helm Chart

This chart deploys `demo-api` in the local sandbox and renders the formal
aws-dev, aws-test, and aws-prod profiles. AWS releases load two ordered files:

```text
values/environments/<environment>.yaml
values/releases/<environment>.yaml
```

Environment values own runtime configuration. Release values own only image
and delivery identity. The release file is loaded second so an approved
artifact identity overrides the chart defaults without copying hostnames,
resource settings, Secret references, or database configuration.

## Local Render Test

```bash
cd apps/demo-api/helm
helm template demo-api . --namespace startup-apps
```

## Local Install Test

```bash
kubectl create namespace startup-apps --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install demo-api . --namespace startup-apps
```

## Port Forward Test

```bash
kubectl -n startup-apps port-forward svc/demo-api 8080:80
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/version
curl http://localhost:8080/metrics
curl http://localhost:8080/db/health
```

## Image Note

For the local kind workflow, build the image and load it into the kind cluster before syncing the Argo CD application:

```bash
./scripts/build-load-demo-api-image.sh
```

The normal aws-dev path is the metadata-driven Promotion PR created by
`.github/workflows/demo-api-image-publish.yaml`. It updates the image tag,
digest, application version, full source commit, and build workflow run ID in
`values/releases/aws-dev.yaml` only.

After the aws-dev PR is merged and its desired state is ready for advancement,
run `.github/workflows/demo-api-promote-environment.yaml` from `main`. It allows
only `aws-dev -> aws-test` and `aws-test -> aws-prod`, verifies the exact GHCR
digest, and opens a PR that changes only the target release file. Validation
evidence becomes a required cross-environment gate in v0.9.4.

The lower-level manual image command remains available for troubleshooting:

```bash
VALUES_FILE=apps/demo-api/helm/values/releases/aws-dev.yaml \
IMAGE_TAG=sha-<short-commit> \
IMAGE_DIGEST=sha256:<64-character-digest> \
./scripts/set-demo-api-image.sh
```

Render an AWS profile with both layers in this order:

```bash
helm template demo-api apps/demo-api/helm \
  --values apps/demo-api/helm/values/environments/aws-dev.yaml \
  --values apps/demo-api/helm/values/releases/aws-dev.yaml
```

When `image.digest` is set, the chart renders `repository@sha256:digest`.
`image.tag` remains the readable application version. The local image helper
clears the digest and restores tag-based kind loading.

The chart projects delivery identity into workload and Pod annotations under
`platform.startup.dev/*`. Validate the live aws-dev chain with:

```bash
./scripts/validate-demo-api-delivery-trace.sh
```

The AWS environment values reference `startup-apps/demo-api-postgresql` inside
their independent clusters. Create or refresh that runtime Secret with
`scripts/sync-demo-api-postgresql-secret.sh`; never commit its value.
