# Progressive Delivery

v0.3 introduces Argo Rollouts for progressive delivery.

## Goal

The demo-api workload is changed from a standard Kubernetes Deployment to an Argo Rollouts Rollout.

This enables:

- canary rollout steps
- manual promotion
- abort and rollback workflows
- visible rollout state

## Local v0.3 Strategy

The local kind version uses replica-based canary behavior.

```text
Git push
  |
  v
Argo CD sync
  |
  v
Rollout resource
  |
  v
Argo Rollouts controller
  |
  v
ReplicaSets / Pods
```

The default canary steps are:

```yaml
steps:
  - setWeight: 20
  - pause: {}
  - setWeight: 50
  - pause:
      duration: 30s
  - setWeight: 100
```

## Important Note

Without ingress traffic routing or service mesh, `setWeight` primarily demonstrates rollout progression and pod/ReplicaSet behavior.

Strict L7 traffic splitting will be introduced later with ingress-nginx traffic routing.

## Validate Controller

```bash
kubectl get pods -n argo-rollouts
kubectl get application argo-rollouts -n argocd
```

## Validate Rollout

```bash
kubectl get rollout -n startup-apps
kubectl argo rollouts get rollout demo-api -n startup-apps
```

## Watch Rollout

```bash
./scripts/rollout-status.sh
```

## Promote Rollout

```bash
./scripts/rollout-promote.sh
```

## Abort Rollout

```bash
./scripts/rollout-abort.sh
```
