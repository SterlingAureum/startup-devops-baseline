# DemoApiDependencySuccessRatioLowWarning

## Meaning

A demo-api dependency received checks and its five-minute success ratio stayed
below 99 percent for 10 minutes.

## Impact

Readiness, database-backed requests, or other dependency-backed operations may
be intermittently degraded even when the HTTP service remains reachable.

## First response

1. Record the `dependency`, environment, cluster, service version, and release
   ID labels.
2. Inspect the Data Overview Dashboard and correlate dependency failures with
   HTTP success ratio and latency.
3. Run read-only checks:

```bash
kubectl -n startup-apps get rollout,pods,svc
kubectl -n startup-apps logs -l app.kubernetes.io/name=demo-api --since=20m --tail=200
kubectl -n data-platform get pods,svc 2>/dev/null || true
```

Query `demo_api:dependency_success_ratio:rate5m` and
`data:demo_api_dependency_checks:rate5m` for the affected dependency. Confirm
that checks are present and distinguish failure from no-data.

## Diagnosis and recovery

- Verify network policy, Service discovery, credentials delivery, and the
  dependency's own health without printing secret values.
- In AWS, inspect CloudNativePG status and collector signals when the dependency
  is PostgreSQL.
- Do not rotate credentials, restart PostgreSQL, or perform a switchover from
  this Runbook alone.

Resolve when the dependency success ratio stays at or above 99 percent with
checks present and application readiness is healthy. Record whether the cause
was application, network, secret delivery, or dependency runtime.
