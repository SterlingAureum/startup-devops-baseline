# DemoApiDependencySuccessRatioLowCritical

## Meaning

A demo-api dependency received checks and its five-minute success ratio stayed
below 90 percent for 5 minutes. This critical alert inhibits the warning alert
for the same environment, cluster, component, and alert family.

## Impact

Dependency-backed application functions are likely unavailable or severely
degraded. HTTP readiness or error-rate alerts may fire as a consequence.

## First response

1. Record the dependency, release identity, alert start time, and correlated
   HTTP and Rollout state.
2. Run read-only checks:

```bash
kubectl -n startup-apps get rollout,pods,endpoints
kubectl -n startup-apps logs -l app.kubernetes.io/name=demo-api --since=15m --tail=300
kubectl -n data-platform get cluster,pods,svc 2>/dev/null || true
kubectl -n external-secrets get externalsecret 2>/dev/null || true
```

Never print Kubernetes Secret data. Query dependency outcome rates by
`dependency`, `service_version`, and `platform_release_id` and correlate them
with PostgreSQL collection and target-health signals.

## Diagnosis and recovery

- If credentials or ExternalSecret reconciliation failed, use the reviewed
  secret-recovery procedure without exposing the credential.
- If CloudNativePG is unhealthy, follow its operator status and recovery
  procedures; do not force a switchover without explicit approval.
- If the release introduced an incompatible dependency change, use the
  reviewed environment rollback path.
- Production mutations remain human-approved.

Resolve only after dependency checks remain successful, demo-api readiness is
healthy, and correlated HTTP, target, and database alerts have cleared.
Preserve the incident timeline and recovery evidence.
