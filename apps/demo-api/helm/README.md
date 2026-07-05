# demo-api Helm Chart

This chart deploys the `demo-api` service for the local GitOps baseline.

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
```

## Image Note

For the local kind workflow, build the image and load it into the kind cluster before syncing the Argo CD application:

```bash
./scripts/build-load-demo-api-image.sh
```

The default image is:

```text
startup-devops-baseline/demo-api:0.1.0
```
