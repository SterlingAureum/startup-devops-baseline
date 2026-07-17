# Argo Rollouts Analysis Flow

## Components

Prometheus canary analysis in this repository depends on three components:

```text
Argo CD:
  syncs manifests from Git

Argo Rollouts:
  owns Rollout, AnalysisTemplate, and AnalysisRun behavior

Prometheus:
  provides metrics queried by AnalysisRun
```

## Resource ownership

`AnalysisTemplate` is not a separate Argo CD Application.

It is rendered by the existing `demo-api` Helm chart and managed by the existing `demo-api` Application.

```text
startup-devops-root Application
  -> demo-api Application
     -> apps/demo-api/helm
        -> Rollout
        -> Services
        -> Ingress
        -> AnalysisTemplate
```

## AnalysisTemplate vs AnalysisRun

`AnalysisTemplate` is the reusable template:

```text
AnalysisTemplate/demo-api-canary-health
```

`AnalysisRun` is the execution created during a rollout:

```text
AnalysisRun/demo-api-xxxxx
```

A new AnalysisRun is created when the Rollout reaches an analysis step.

## Current query

The v0.3.3 baseline uses:

```promql
sum(up{job="demo-api-canary"})
```

Success condition:

```text
result[0] >= 1
```

This checks whether Prometheus can scrape the canary service.

## Rollout progression

The current intended flow is:

```text
1. new image tag is committed to values.yaml
2. Argo CD syncs the demo-api Application
3. Argo Rollouts creates a new ReplicaSet
4. 20% canary traffic is routed to the new ReplicaSet
5. rollout pauses for 60 seconds
6. AnalysisRun queries Prometheus
7. if successful, rollout continues
8. rollout reaches manual pause at 50%
9. operator runs promote
10. rollout moves to 100%
11. new ReplicaSet becomes stable
12. old ReplicaSet is scaled down
```

## Why a successful AnalysisRun may still show Rollout Paused

The analysis step only validates the canary gate.

The rollout can still pause later if the strategy contains:

```yaml
pause: {}
```

That is an indefinite manual pause.

Continue with:

```bash
kubectl argo rollouts promote demo-api -n startup-apps
```

Abort with:

```bash
kubectl argo rollouts abort demo-api -n startup-apps
```

## Interpreting INFO such as "✔ 2"

If the AnalysisRun displays:

```text
✔ 2
```

It means the metric produced two successful measurements.

This corresponds to:

```yaml
count: 2
```

in the analysis metric configuration.

## Validation commands

```bash
kubectl -n startup-apps get analysistemplate
kubectl -n startup-apps get analysisrun
kubectl argo rollouts get rollout demo-api -n startup-apps
kubectl -n startup-apps describe analysisrun <analysisrun-name>
```
