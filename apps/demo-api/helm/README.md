# demo-api Helm Chart

This chart deploys `demo-api` in both the local and aws-dev GitOps
environments. Database integration is disabled by default and enabled only by
`values-aws-dev.yaml`.

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

The normal AWS path is the metadata-driven Promotion PR created by
`.github/workflows/demo-api-image-publish.yaml`. It updates the image tag,
digest, application version, full source commit, and build workflow run ID in
`values-aws-dev.yaml`.

The lower-level manual image command remains available for troubleshooting:

```bash
VALUES_FILE=apps/demo-api/helm/values-aws-dev.yaml \
IMAGE_TAG=sha-<short-commit> \
IMAGE_DIGEST=sha256:<64-character-digest> \
./scripts/set-demo-api-image.sh
```

When `image.digest` is set, the chart renders `repository@sha256:digest`.
`image.tag` remains the readable application version. The local image helper
clears the digest and restores tag-based kind loading.

The chart projects delivery identity into workload and Pod annotations under
`platform.startup.dev/*`. Validate the live aws-dev chain with:

```bash
./scripts/validate-demo-api-delivery-trace.sh
```

The AWS values reference `startup-apps/demo-api-postgresql`. Create or refresh
that runtime Secret with `scripts/sync-demo-api-postgresql-secret.sh`; never
commit its value.
