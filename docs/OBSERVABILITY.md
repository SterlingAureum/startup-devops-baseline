# Observability

The active v0.11.2 telemetry foundation uses Prometheus Operator through the
GitOps-managed `kube-prometheus-stack` release. The original hand-written
Prometheus resources remain under `platform/monitoring/prometheus` as
historical v0.1 material and are no longer referenced by an active Argo CD
Application.

## Active Components

```text
observability Namespace
  Prometheus Operator
  Prometheus StatefulSet
  kube-state-metrics
  node-exporter DaemonSet
  ServiceMonitor resources
```

Grafana, Alertmanager, default alert rules, Loki, Alloy, tracing, Thanos, and
remote write are not part of v0.11.2.

The local Application is:

```text
clusters/local/platform/templates/monitoring.yaml
```

The AWS base Application and environment patches are:

```text
clusters/aws/base/platform/monitoring.yaml
clusters/aws/overlays/dev/kustomization.yaml
clusters/aws/overlays/test/kustomization.yaml
clusters/aws/overlays/prod/kustomization.yaml
```

## demo-api Metrics

demo-api exposes `/metrics` and owns its ServiceMonitor in the application
Chart. It discovers the `demo-api`, `demo-api-stable`, and `demo-api-canary`
Services and uses their Service names as the Prometheus `job` label. This keeps
the original Canary query valid:

```promql
sum(up{job="demo-api-canary"})
```

Example application metrics include:

```text
demo_api_http_requests_total
demo_api_http_request_duration_seconds
demo_api_dependency_checks_total
demo_api_dependency_check_duration_seconds
process_open_fds
process_max_fds
python_info
```

## Check the Local Stack

```bash
kubectl get application monitoring -n argocd
kubectl get pods -n observability
kubectl get servicemonitors -n startup-apps
./scripts/check-monitoring.sh
```

Generate demo-api traffic if the application metric is not visible yet, then
wait for the next scrape interval.

## Query Prometheus

```bash
kubectl -n observability port-forward \
  svc/observability-metrics-prometheus 19090:9090
```

Then query:

```bash
curl -fsS http://127.0.0.1:19090/-/ready
curl -fsS --get http://127.0.0.1:19090/api/v1/query \
  --data-urlencode 'query=demo_api_http_requests_total'
```

`scripts/validate.sh` creates its own temporary port-forward unless
`SKIP_PROMETHEUS_HTTP=true` is set.

## Detailed v0.11 Contracts

- `docs/V0.11_OBSERVABILITY_SRE_DESIGN.md` defines the complete v0.11 line.
- `docs/V0.11.1_METRICS_FOUNDATION.md` defines the current metrics deployment,
  migration, storage, scheduling, NetworkPolicy, and live-validation steps.
- `docs/V0.11.2_APPLICATION_PLATFORM_TELEMETRY.md` defines application-owned
  discovery, bounded metrics, Pod-derived release correlation, and telemetry
  acceptance.
