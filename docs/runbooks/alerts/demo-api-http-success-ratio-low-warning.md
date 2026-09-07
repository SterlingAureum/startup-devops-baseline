# DemoApiHttpSuccessRatioLowWarning

## Meaning

demo-api received traffic and its five-minute HTTP success ratio stayed below
99 percent for 10 minutes. This is degraded service quality, not yet the
critical threshold.

## Impact

Some callers may receive `5xx` responses. A release, dependency, or transient
capacity problem may be developing.

## First response

1. Record the alert labels, start time, environment, cluster, service version,
   and release ID.
2. Open the Service Overview Dashboard and compare request rate, success ratio,
   error rate, and p95 latency.
3. Run read-only checks:

```bash
kubectl -n startup-apps get rollout,pods,svc
kubectl -n startup-apps describe rollout demo-api
kubectl -n startup-apps logs -l app.kubernetes.io/name=demo-api --since=20m --tail=200
```

Query `demo_api:http_success_ratio:rate5m` and
`demo_api:http_errors:rate5m` by `service_version` and
`platform_release_id`. Confirm that traffic exists before interpreting the
ratio.

## Diagnosis and recovery

- If one release ID owns the errors, compare it with the reviewed GitOps
  release and the Rollout state.
- If dependency failures rise at the same time, follow the matching dependency
  Runbook before changing the application.
- If telemetry is missing, inspect Prometheus target discovery separately; if
  a supporting Deployment is unavailable, follow
  `KubernetesDeploymentUnavailable`.
- Do not restart, promote, abort, or roll back production from this Runbook.
  Use the repository's reviewed environment-specific delivery procedure.

The alert is resolved when request traffic remains present and the success
ratio stays at or above 99 percent for the next evaluation windows. Record the
cause, affected release, action, and recovery time.
