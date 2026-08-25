# Observability

The active v0.11.4.2.2 telemetry and operator-view foundation uses Prometheus Operator through the
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
  PodMonitor resources in AWS profiles
  Grafana Deployment and private ClusterIP Service
  Git-provisioned Dashboard ConfigMaps
  PrometheusRule recording rules
  Capacity and resource-efficiency recording rules
```

Alertmanager, alert rules, Loki, Alloy, tracing, Thanos, remote write, Kubecost,
and cloud billing integration are not part of v0.11.4.2.2.

Local acceptance sources `scripts/lib/observability-live.sh`. A target must
produce a numeric `up` value of at least one; discovery alone is insufficient.
The shared preflight generates bounded application traffic, verifies populated
HTTP and dependency metrics directly from the deployed image, and prints the
active target `lastError` plus runtime image ownership when a check fails.

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

The repository-owned views Chart and local/AWS Applications are:

```text
platform/observability/helm
clusters/local/platform/templates/observability-views.yaml
clusters/aws/base/platform/observability-views.yaml
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
./scripts/check-observability-views.sh
PROFILE=local ./scripts/check-controller-metrics.sh
PROFILE=local ./scripts/check-operator-dashboards.sh
PROFILE=local ./scripts/check-capacity-signals.sh
PROFILE=local ./scripts/check-capacity-dashboard.sh
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
- `docs/V0.11.4.0_GRAFANA_RECORDING_RULES.md` defines private Grafana,
  repository-owned views, recording rules, Dashboard provisioning, and local
  acceptance.
- `docs/V0.11.4.1.0_CONTROLLER_METRICS_DISCOVERY.md` defines immutable
  controller versions, controller and data monitors, diagnostic recording
  rules, and profile-aware live discovery.
- `docs/V0.11.4.1.1_OPERATOR_DASHBOARDS.md` defines the immutable Delivery,
  Data, and Platform Dashboards, recording-rule query boundary, conditional
  CloudNativePG no-data behavior, and profile-aware live acceptance.
- `docs/V0.11.4.2.0_CAPACITY_SIGNAL_FOUNDATION.md` defines existing-source
  capacity and efficiency signals, active workload semantics, bounded request
  coverage, cost boundaries, and profile-aware live discovery.
- `docs/V0.11.4.2.1_CAPACITY_EFFICIENCY_DASHBOARD.md` defines the immutable
  Capacity and Resource Efficiency Dashboard, recording-rule-only query
  boundary, interpretation policy, live acceptance, and clean replay handoff.
