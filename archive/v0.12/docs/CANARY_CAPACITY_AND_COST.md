# Canary Capacity and Cost

## Summary

Canary rollout improves release safety, but it can temporarily increase resource usage because old and new versions may run at the same time.

This matters for:

```text
- memory-heavy API services
- JVM services with large heap
- ML inference services
- GPU model serving workloads
```

## Example

Normal state:

```text
10 replicas
20Gi memory per replica
normal capacity = 200Gi memory
```

If a rollout temporarily runs old and new versions at full size:

```text
old version: 10 replicas x 20Gi = 200Gi
new version: 10 replicas x 20Gi = 200Gi
peak = 400Gi
```

For GPU workloads:

```text
stable version: 10 GPU pods
canary version: 10 GPU pods
peak = 20 GPUs
```

This can be too expensive or impossible if spare GPU capacity is unavailable.

## Controls

### maxSurge

`maxSurge` controls how many extra pods may be created above the desired replica count.

Example:

```yaml
strategy:
  canary:
    maxSurge: 1
```

This means the rollout can temporarily create at most one extra pod above desired replicas.

### maxUnavailable

`maxUnavailable` controls how many pods may be unavailable during rollout.

Example:

```yaml
strategy:
  canary:
    maxUnavailable: 0
```

This keeps availability conservative: do not intentionally reduce available capacity during rollout.

### dynamicStableScale

For traffic-routed canary rollouts, `dynamicStableScale` can reduce the stable ReplicaSet as canary weight increases.

This can lower resource cost, but it weakens instant rollback capacity because the stable version may need time to scale back up.

This baseline does not enable it by default.

## Baseline choice

For this local baseline:

```yaml
maxSurge: 1
maxUnavailable: 0
```

This keeps the rollout safe and bounded while still demonstrating progressive delivery.

## Production guidance

For ordinary stateless web services:

```text
- maxSurge: 10% or a small fixed number
- maxUnavailable: 0 or small percentage
- use metrics-based analysis before final promotion
```

For GPU or model-serving workloads:

```text
- avoid full stable + full canary duplication unless capacity is reserved
- use very small canary pools
- route by gateway, tenant, header, or internal users
- keep stable capacity available for rollback
- evaluate cost, latency, and model quality before increasing traffic
```

## Key idea

Canary is not free.

It trades temporary extra capacity for safer releases and faster rollback.
