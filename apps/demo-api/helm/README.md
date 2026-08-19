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
digest, and opens a PR that changes only the target release file. First run
`.github/workflows/demo-api-record-release-evidence.yaml` for the source
environment, review and merge its evidence-only PR, then pass that workflow
run ID to the promotion workflow. Evidence must be present on `main`, fresh,
and byte-bound to the current source release. v0.9.5 also requires a reviewed
AWS runtime record from `evidence/demo-api/runtime/<source>/<id>.json`; collect
it from the restricted local operations path after the source runtime has
converged.

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

v0.11.2 also renders an application-owned ServiceMonitor. Its target relabeling
copies the application version, environment, deterministic release ID, source
commit, and image digest from each selected Pod. Pod metadata is intentional:
during a Canary, the stable and canary Services can select different
ReplicaSets and must not receive one Service-level release identity.

Configure bounded discovery under:

```yaml
telemetry:
  metrics:
    serviceMonitor:
```

The Prometheus control plane discovers this resource; the monitoring
Application no longer embeds demo-api-specific scrape configuration.

aws-test and aws-prod enable Argo Rollouts ALB traffic routing. Their Ingress
uses the `use-annotation` action backend, while Rollouts owns the stable/canary
weights and Service selectors. The inline Web AnalysisRun checks canary
database readiness and exact environment/version identity without introducing
the full production observability stack planned for v1.0.

The AWS environment values reference `startup-apps/demo-api-postgresql` inside
their independent clusters. Create or refresh that runtime Secret with
`scripts/sync-demo-api-postgresql-secret.sh`; never commit its value.
