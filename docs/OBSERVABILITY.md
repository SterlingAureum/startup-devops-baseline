# Observability

The v0.1 baseline includes basic Prometheus monitoring.

The goal is not to provide a full production observability stack. The goal is to prove that the demo workload exposes metrics and that Prometheus can scrape and query them.

## Components

```text
monitoring namespace
  |
  +-- prometheus Deployment
  +-- prometheus Service
  +-- prometheus ConfigMap
```

Prometheus resources are stored under:

```text
platform/monitoring/prometheus/
```

The Argo CD Application is stored at:

```text
clusters/local/platform/monitoring.yaml
```

## demo-api Metrics

The demo API exposes Prometheus metrics at:

```text
/metrics
```

Example metrics:

```text
demo_api_requests_total
demo_api_request_duration_seconds
process_open_fds
process_max_fds
python_info
```

## Check Monitoring Resources

```bash
kubectl get pods -n monitoring
kubectl get svc -n monitoring
kubectl get application monitoring -n argocd
```

Expected Application status:

```text
monitoring   Synced   Healthy
```

## Query Prometheus Manually

Port-forward Prometheus:

```bash
kubectl -n monitoring port-forward svc/prometheus 19090:9090
```

Then query:

```bash
curl http://localhost:19090/-/ready
curl 'http://localhost:19090/api/v1/query?query=demo_api_requests_total'
```

Generate demo-api traffic if the metric is not visible yet:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

Wait for the next Prometheus scrape interval, then query again.

## validate.sh Behavior

The validation script automatically creates a temporary port-forward for Prometheus checks. It does not rely on fixed `localhost:9090`, because that port may already be used by another local Prometheus.

Run:

```bash
./scripts/validate.sh
```

Skip Prometheus HTTP checks:

```bash
SKIP_PROMETHEUS_HTTP=true ./scripts/validate.sh
```

Use an external Prometheus endpoint explicitly:

```bash
PROMETHEUS_HTTP_MODE=external \
PROMETHEUS_BASE_URL=http://localhost:9090 \
./scripts/validate.sh
```

## Current Limitations

v0.1 does not include:

- Grafana dashboards.
- Alertmanager.
- Prometheus Operator.
- ServiceMonitor CRDs.
- kube-state-metrics.
- node-exporter.
- Loki or log aggregation.
- Alert routing.

These can be added in future versions.
