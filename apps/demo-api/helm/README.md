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

The committed default is an immutable GHCR image. Promote a newly published
AWS image with:

```bash
VALUES_FILE=apps/demo-api/helm/values-aws-dev.yaml \
IMAGE_TAG=sha-<short-commit> \
./scripts/set-demo-api-image.sh
```

The AWS values reference `startup-apps/demo-api-postgresql`. Create or refresh
that runtime Secret with `scripts/sync-demo-api-postgresql-secret.sh`; never
commit its value.
