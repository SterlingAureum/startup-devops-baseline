# Observability

This document describes the basic observability setup used by the local GitOps baseline.

The current version uses a lightweight standalone Prometheus deployment. It is intentionally simple and is not intended to replace a production-grade monitoring stack.

## Scope

The v0.1 monitoring scope includes:

- A `monitoring` namespace.
- A standalone Prometheus deployment.
- A Prometheus scrape config for the `demo-api` service.
- A Prometheus service for local port-forward access.
- Validation checks for Prometheus readiness and demo-api metrics ingestion.

The current version does not include:

- Grafana dashboards.
- Alertmanager.
- Prometheus Operator.
- ServiceMonitor resources.
- kube-state-metrics.
- node-exporter.
- Long-term metrics storage.
- Production alerting rules.

These can be added in later versions.

## GitOps Flow

The monitoring stack is managed by Argo CD.

The root application reads:

```text
clusters/local/platform/
```

The monitoring application is defined at:

```text
clusters/local/platform/monitoring.yaml
```

It deploys manifests from:

```text
platform/monitoring/prometheus/
```

The expected Argo CD application tree is:

```text
startup-devops-root
  ├── ingress-nginx
  ├── demo-api
  └── monitoring
```

## Prometheus Scrape Configuration

The Prometheus configuration is stored in:

```text
platform/monitoring/prometheus/configmap.yaml
```

The demo-api scrape target is:

```text
demo-api.startup-apps.svc.cluster.local:80
```

The metrics path is:

```text
/metrics
```

## Deploy Monitoring

After applying this patch, commit and push the changes to the Git repository watched by Argo CD:

```bash
git status
git add .
git commit -m "feat: add basic prometheus monitoring"
git push
```

Refresh the root application if needed:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

Check Argo CD applications:

```bash
kubectl get applications -n argocd
```

Expected result:

```text
NAME                  SYNC STATUS   HEALTH STATUS
demo-api              Synced        Healthy
ingress-nginx         Synced        Healthy
monitoring            Synced        Healthy
startup-devops-root   Synced        Healthy
```

## Validate Prometheus

Check the monitoring namespace:

```bash
kubectl get pods -n monitoring
kubectl get svc -n monitoring
```

Port-forward Prometheus:

```bash
kubectl -n monitoring port-forward svc/prometheus 9090:9090
```

In another terminal, check readiness:

```bash
curl http://localhost:9090/-/ready
```

Query demo-api metrics:

```bash
curl 'http://localhost:9090/api/v1/query?query=demo_api_requests_total'
```

You can also open Prometheus in a browser:

```text
http://localhost:9090
```

Then query:

```promql
demo_api_requests_total
```

## Run Full Validation

The validation script includes monitoring checks:

```bash
./scripts/validate.sh
```

It checks:

- Argo CD applications.
- demo-api workload.
- ingress access.
- Prometheus deployment.
- Prometheus readiness.
- demo-api metrics query through Prometheus.

## Troubleshooting

If the `monitoring` application does not appear, refresh the root application:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

If Prometheus is not ready, check the pod logs:

```bash
kubectl logs -n monitoring deploy/prometheus
```

If Prometheus is running but the demo-api query returns no data, generate demo-api traffic first:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

Wait for at least one scrape interval, then query again:

```bash
curl 'http://localhost:9090/api/v1/query?query=demo_api_requests_total'
```
