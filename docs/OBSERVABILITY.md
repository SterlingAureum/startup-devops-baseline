# Observability

The active v0.11.6.1.2.2 local observability foundation uses Prometheus Operator through the
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
  Alertmanager StatefulSet and private ClusterIP Service
  Environment-local routing and inhibition configuration
  Internal-only drill webhook routes, inactive until a guarded drill creates the sink
  Loki Monolithic StatefulSet and private gateway
  Alloy Pod-log collector DaemonSet
  Alloy Kubernetes Event collector singleton Deployment
  Grafana-provisioned private Loki data source
```

Nine repository-owned actionable alerts and their version-controlled Runbooks
remain active and unchanged. v0.11.5.2.0 adds a guarded local firing,
resolution, routing, and inhibition drill through a temporary restricted sink.
External notification providers, tracing, Thanos, remote write, Kubecost, and
cloud billing integration are not part of this increment.

The v0.11.5.0.1 repair changes only active-configuration acceptance: both the
spaced repository matcher and Alertmanager's compact canonical matcher are
accepted while route and inhibition cardinality remain exact. It changes no
runtime resource and requires no redeployment.

The v0.11.5.1.1 PrometheusRule consumes only accepted `demo_api:`, `delivery:`,
`platform:`, and `data:` recording rules. A clean baseline must keep all nine
alerts inactive; missing local CloudNativePG data remains no-data. The repaired
target-down rule uses `up == bool 0`, so up targets contribute zero and down
targets contribute one while absent namespace/job groups remain no-data.

Local acceptance sources `scripts/lib/observability-live.sh`. A target must
produce a numeric `up` value of at least one; discovery alone is insufficient.
The shared preflight generates bounded application traffic, verifies populated
HTTP and dependency metrics directly from the deployed image, and prints the
active target `lastError` plus runtime image ownership when a check fails.

The v0.11.5.1.1.1 acceptance repair makes the neutral feature baseline an
explicit replay start state rather than a reusable observability image. Local
acceptance builds a unique image from the exact feature commit and requires
both `demo_api_http_requests_total` and `demo_api_dependency_checks_total`.
The target-down live check validates ownership through the Chart-declared
`PrometheusRule/operator-diagnostic-recording-rules`; it does not look for the
nonexistent `operator-recording-rules` name.

The first v0.11.5.2.0 live attempt confirmed both drill receivers, both webhook
integrations, and both resolved-delivery settings. Alertmanager represented
each active webhook URL as `url: <secret>` in `/api/v2/status`.
v0.11.5.2.0.1 therefore separates exact literal desired-state validation from
exact redacted runtime validation. Global defaults such as `slack_app_url` do
not represent configured external receivers; actual external receiver blocks
remain forbidden. No monitoring redeployment is required for the corrected
checker rerun.

The corrected parser rerun passed, and the subsequent drill proved warning
firing delivery. It then exposed a separate transition defect: deleting the
temporary PrometheusRule did not reliably produce resolved delivery for the
same alert instance. v0.11.5.2.0.2 keeps the rule loaded, changes its expression
from `vector(1)` to the empty-vector `vector(0) == 1`, waits for Prometheus to
clear the alert and Alertmanager to deliver the resolved webhook, and deletes
the rule only as cleanup. Preflight and final checks reject every active
`drill="true"` alert, including one retained from an earlier failed run. This
script-only repair requires neither monitoring redeployment nor an image
rebuild.

The v0.11.5.2.0.2 rerun completed all four phases and left both temporary
alerts healthy and inactive. Its immediate final inventory check nevertheless
observed those two definitions alongside the exact nine formal alerts.
v0.11.5.2.0.3 distinguishes Kubernetes deletion from asynchronous Prometheus
rule inventory convergence: normal final deletion is strict, and a bounded
wait requires both temporary alert definitions to disappear before the formal
baseline is checked. EXIT-trap cleanup remains best-effort so an earlier error
is preserved while cleanup is still attempted. No runtime redeployment or
image rebuild is required.

The repaired v0.11.5.2.0.3 full local rerun passed and closes v0.11.5 locally.
v0.11.6.0 begins the next line with a design-only contract for per-environment
centralized logging and minimal tracing. Alloy will collect Pod logs and
Kubernetes Events into environment-local Loki. An upstream OpenTelemetry
Collector will receive OTLP and export the bounded HTTP-to-demo-api-to-
PostgreSQL trace into environment-local Tempo. Trace IDs, release IDs, source
commits, image digests, Pod identities, and request identities remain parsed
fields rather than Loki labels. No Loki, Alloy, Collector, or Tempo runtime is
deployed in v0.11.6.0.

v0.11.6.1.0 implements the demo-api side of that contract. The process emits
one bounded JSON object per stdout line and derives release identity from the
existing Pod annotations through the Downward API. Successful `/health`,
`/ready`, and `/metrics` requests remain quiet, while their failures are
recorded. Uvicorn uses the same JSON formatter and its duplicate access stream
is disabled. Loki, Alloy, Kubernetes Event collection, Grafana log data
sources, and tracing remain undeployed at this checkpoint.

v0.11.6.1.1 implements the local Pod-log transport and store. The
v0.11.6.1.1.5 repair bounds each node-local Alloy instance to `startup-apps`
Pod logs after cluster-wide Kubernetes API readers exhausted fsnotify watchers
on the dense one-node kind profile. The collector still needs no host
filesystem mount, privileged container, or host sysctl mutation. Loki runs in
Monolithic mode with one replica, filesystem-backed TSDB v13 storage on a
2 GiB disposable `emptyDir`, and 24-hour retention. Its gateway is
ClusterIP-only. NetworkPolicy limits collector access to DNS, the Kubernetes
API, and the Loki gateway.

Only `environment`, `cluster`, `namespace`, `application`, `container`, and
`severity` are indexed Loki labels. Pod name and UID are structured metadata;
release ID, source commit, image digest, request ID, trace ID, and span ID stay
inside the JSON log record. This prevents unbounded stream cardinality while
retaining release correlation.

Loki query results merge structured metadata into each returned label map, so
the Series API, rather than the query-label representation, is the acceptance
source for actual indexed stream labels.

v0.11.6.1.2 adds a separate one-replica Alloy Deployment for Kubernetes
Events. It watches Events in all namespaces with only `get`, `list`, and
`watch` permission on the Event resource. Source records are JSON Lines and use
the same exact six-label index contract, with fixed
`application=kubernetes-events`, `container=events`, and `severity=INFO`.
Changing Event reason, message, object name, and UID stay inside the JSON line.

The collector mounts the local
`observability-events-collector-storage` 256Mi PVC at `/var/lib/alloy`, keeping
the source positions file across collector Pod replacement. The local live
acceptance rejects replay of a deterministic Event after a Deployment restart
and proves that a new Event is still collected afterward.

The local `standard` StorageClass uses `WaitForFirstConsumer`. Repair
v0.11.6.1.2.1 therefore places the Root-owned claim and the
`logging-alloy-events` Application in the same sync wave. The version-specific
deadlock signature and recovery procedure are in
`V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md`.

Repair v0.11.6.1.2.2 changes only the temporary acceptance Event timestamp.
It emits RFC 3339 UTC with exactly six fractional digits, matching Kubernetes
`MicroTime`; the deployed logging topology and data contracts remain unchanged.
The active v0.11.6.1.2.1 local observability foundation therefore remains the
runtime predecessor; v0.11.6.1.2.2 changes only its live checker.

Grafana remains owned by `kube-prometheus-stack`. Its Git-provisioned Loki data
source uses UID `loki`, proxy access, and the private Loki gateway. It is not
default or UI-editable, and Grafana's NetworkPolicy permits only the internal
gateway port required for server-side queries. Validate this runtime with:

```bash
./scripts/check-local-logging-runtime.sh
./scripts/check-local-events-grafana.sh
```

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
./scripts/check-alertmanager.sh
./scripts/check-observability-views.sh
PROFILE=local ./scripts/check-controller-metrics.sh
PROFILE=local ./scripts/check-operator-dashboards.sh
PROFILE=local ./scripts/check-capacity-signals.sh
PROFILE=local ./scripts/check-capacity-dashboard.sh
./scripts/check-actionable-alerts.sh
./scripts/check-prometheus-target-counts.sh
CONFIRM_ALERT_DRILL=true ./scripts/check-alert-lifecycle-drill.sh
./scripts/check-local-logging-runtime.sh
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
- `docs/V0.11.5.2.0_ALERT_LIFECYCLE_DRILL.md` defines the guarded synthetic
  alert lifecycle, continued severity routing, inhibition cases, restricted
  webhook sink, resolved delivery, and zero-residual local acceptance.
