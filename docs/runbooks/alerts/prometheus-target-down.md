# PrometheusTargetDown

## Meaning

At least one required Prometheus scrape target in a platform, application,
delivery, or data namespace has remained down continuously for 10 minutes.

## Impact

Metrics from the affected target are unavailable. Dashboards, recording rules,
and alerts that depend on those metrics can become incomplete or no-data even
when the monitored workload itself is still serving traffic.

## First response

1. Record the alert namespace, job, environment, and cluster labels.
2. Inspect Prometheus target health and the owning Argo CD Application.
3. Run read-only checks:

```bash
kubectl -n observability get prometheus,servicemonitor,podmonitor -o wide
kubectl -n <namespace> get service,endpoints,pods -o wide
kubectl -n <namespace> get events --sort-by=.lastTimestamp
kubectl -n argocd get applications -o wide
```

Use the Prometheus Targets view to capture the scrape URL, last scrape time,
and last error. Do not assume that a missing series means a healthy target.

## Diagnosis and recovery

- Identify whether discovery, network reachability, TLS or authentication,
  endpoint selection, the metrics path, or the exporter process is failing.
- Compare ServiceMonitor or PodMonitor selectors and ports with the live
  Service, Endpoints, and Pod labels at the exact reviewed Git revision.
- Confirm that NetworkPolicy permits the monitoring namespace to reach the
  target and that the metrics endpoint returns a valid Prometheus payload.
- Apply configuration corrections through GitOps. Production restart,
  rollback, scaling, credential rotation, or network-policy changes remain
  reviewed and approved.

Resolve when the target is continuously up, the repaired recording rule is
zero for the affected namespace and job, the owning Application is Healthy,
and downstream recording rules have resumed normal evaluation.
