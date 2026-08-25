# DemoApiHttpSuccessRatioLowCritical

## Meaning

demo-api received traffic and its five-minute HTTP success ratio stayed below
95 percent for 5 minutes. This critical alert inhibits the warning alert with
the same environment, cluster, component, and alert family.

## Impact

Material customer-visible request failure is likely. Treat the affected
environment and release as unsafe until the signal is understood.

## First response

1. Record all alert labels and acknowledge the incident through the team's
   environment-owned process.
2. Inspect the Service Overview and Delivery Overview Dashboards.
3. Run read-only checks:

```bash
kubectl -n startup-apps get rollout demo-api -o wide
kubectl -n startup-apps describe rollout demo-api
kubectl -n startup-apps get pods -o wide
kubectl -n startup-apps logs -l app.kubernetes.io/name=demo-api --since=15m --tail=300
```

Query the success ratio and error rate grouped by `service_version` and
`platform_release_id`. Correlate the first failing window with the Git commit,
image digest, Promotion PR, and Rollout revision.

## Diagnosis and recovery

- If the active release introduced the failure, use the reviewed Rollout or
  GitOps rollback procedure for that environment.
- If a dependency is failing, follow the critical dependency Runbook and avoid
  masking the cause with repeated application restarts.
- If the Rollout is unhealthy, also follow `ArgoRolloutProblem`.
- Production rollback, promotion, or Kubernetes writes require the existing
  human approval boundary.

Resolve only after the success ratio recovers to at least 99 percent with
traffic present, the Rollout is Healthy, and no critical dependency or target
alert remains. Preserve incident and release evidence.
