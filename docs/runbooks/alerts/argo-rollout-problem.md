# ArgoRolloutProblem

## Meaning

At least one Argo Rollout stayed in `Degraded`, `Error`, `InvalidSpec`,
`Timeout`, `Abort`, or `Aborted` for 5 minutes.

## Impact

Progressive delivery is blocked or failed. Stable traffic may remain healthy,
but the candidate release must not be promoted until the cause is understood.

## First response

```bash
kubectl -n startup-apps get rollout -o wide
kubectl -n startup-apps describe rollout demo-api
kubectl -n startup-apps get analysisrun,replicaset,pods -o wide
kubectl -n argocd get application demo-api -o wide
```

Record the Rollout revision, current and stable ReplicaSets, AnalysisRun result,
image digest, source commit, release ID, and Argo CD target revision.

## Diagnosis and recovery

- For `InvalidSpec`, compare the rendered Git declaration with the live object.
- For AnalysisRun failure, inspect the Prometheus query result and application
  telemetry before retrying anything.
- For aborted or timed-out progression, determine whether it was an intentional
  operator action.
- Do not manually edit the live Rollout or delete ReplicaSets.
- Use the repository's reviewed promote, retry, abort, or rollback procedure.
  Production progression remains manually approved.

Resolve when the intended Rollout is Healthy, its stable revision matches the
reviewed GitOps release, required Pods are Ready, and related application and
dependency alerts are clear.
