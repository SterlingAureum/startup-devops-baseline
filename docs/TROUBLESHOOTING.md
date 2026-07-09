# Troubleshooting

This document records common issues observed while building and validating the v0.1 local GitOps baseline.

## kube-proxy CrashLoopBackOff: too many open files

Symptom:

```text
kube-proxy CrashLoopBackOff
failed complete: too many open files
```

Possible cause:

The local Docker daemon or Docker networking state may be unhealthy. In the observed case, the kind node container had a high `ulimit -n`, but kube-proxy still failed until Docker was restarted.

Checks:

```bash
kubectl get pods -n kube-system
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=100
docker exec startup-devops-baseline-control-plane sh -c "ulimit -n"
```

Suggested fix:

```bash
sudo systemctl restart docker
```

Then recreate or recheck the kind cluster.

## Argo CD CRD Annotation Too Long

Symptom:

```text
The CustomResourceDefinition "applicationsets.argoproj.io" is invalid:
metadata.annotations: Too long: must have at most 262144 bytes
```

Cause:

Client-side `kubectl apply` stores large manifests in the `kubectl.kubernetes.io/last-applied-configuration` annotation. Some Argo CD CRDs are too large for this limit.

Fix:

Use server-side apply:

```bash
kubectl apply --server-side --force-conflicts \
  -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

The repository install script should already use server-side apply.

## startup-devops-root Application Is Missing

Symptom:

```bash
kubectl get applications -n argocd
```

does not show:

```text
startup-devops-root
```

Cause:

The Application is not created by installing Argo CD. It is created by:

```bash
./scripts/deploy-root-app.sh
```

If the cluster or Argo CD namespace was recreated, the Application must be recreated.

Fix:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

## Argo CD Cannot Pull Repository

Symptoms:

- Application is `OutOfSync` or `Unknown`.
- Application events mention repository access failures.
- Child applications are not created.

Checks:

```bash
kubectl describe application startup-devops-root -n argocd
kubectl logs -n argocd deploy/argocd-repo-server --tail=100
```

Fixes:

- Confirm `REPO_URL` is correct.
- Confirm changes are pushed to GitHub.
- Use a public repository for local demo, or configure repository credentials in Argo CD.

## demo-api Pod Is ImagePullBackOff

Cause:

The image may not have been loaded into the kind cluster.

Fix:

```bash
./scripts/build-load-demo-api-image.sh
kubectl rollout restart deploy/demo-api -n startup-apps
```

Check:

```bash
kubectl get pods -n startup-apps
kubectl describe pod -n startup-apps -l app.kubernetes.io/name=demo-api
```

## Ingress Does Not Work

Checks:

```bash
kubectl get pods -n ingress-nginx
kubectl get ingress -n startup-apps
kubectl get svc -n startup-apps
curl -H "Host: demo-api.local" http://localhost/health
```

If the Host header works but the hostname does not, add:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
```

## Prometheus Port 9090 Already in Use

Symptom:

```text
Unable to listen on port 9090: bind: address already in use
```

Cause:

Another local Prometheus or service is already listening on port 9090.

Check:

```bash
sudo ss -ltnp | grep ':9090'
docker ps | grep 9090
```

Fix:

Use a different local port:

```bash
kubectl -n monitoring port-forward svc/prometheus 19090:9090
```

The optimized `validate.sh` automatically finds a free local port for Prometheus checks.

## Prometheus Query Succeeds but demo-api Metric Is Missing

Cause:

Prometheus may not have scraped demo-api yet, or there has been no recent traffic.

Generate traffic:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

Wait for the next scrape interval and query again.

## Full Validation

Run:

```bash
./scripts/validate.sh
```

If Prometheus HTTP validation is not needed:

```bash
SKIP_PROMETHEUS_HTTP=true ./scripts/validate.sh
```
