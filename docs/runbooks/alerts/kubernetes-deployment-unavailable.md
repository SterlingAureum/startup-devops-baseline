# KubernetesDeploymentUnavailable

## Meaning

A required Deployment in the observability, application, delivery, or data
namespaces reported unavailable replicas continuously for 10 minutes.

## Impact

The affected controller or service may have reduced capacity or be completely
unavailable. Dependent GitOps, monitoring, or application behavior may also be
degraded.

## First response

1. Record the alert namespace, Deployment, environment, and cluster labels.
2. Inspect the Platform Overview Dashboard and related Argo CD Application.
3. Run read-only checks:

```bash
kubectl -n <namespace> get deployment,replicaset,pods -o wide
kubectl -n <namespace> describe deployment <deployment>
kubectl -n <namespace> get events --sort-by=.lastTimestamp
kubectl -n argocd get applications -o wide
```

Check desired, available, and unavailable replica recording rules. Inspect Pod
scheduling, readiness, image-pull, resource, volume, and NetworkPolicy evidence
without deleting or restarting resources.

## Diagnosis and recovery

- Determine whether the Deployment is owned by a repository Application or an
  external Chart before proposing a change.
- Compare the live image, configuration, and replica count with the exact
  reviewed Git revision.
- If rollout or reconciliation is still progressing, preserve its evidence and
  avoid overlapping manual operations.
- Apply configuration corrections through GitOps. Production scaling,
  rollback, restart, or other writes remain reviewed and approved.

Resolve when desired replicas are available, Pods remain Ready, the owning
Application is Healthy, and related application, dependency, or database
alerts have cleared.
