# Rollback Runbook

This runbook describes the v0.3 rollback workflow for demo-api.

## Check Current Rollout

```bash
kubectl argo rollouts get rollout demo-api -n startup-apps
```

## Abort an In-Progress Rollout

Use this when a canary version is paused or unhealthy.

```bash
kubectl argo rollouts abort demo-api -n startup-apps
```

## Promote a Healthy Rollout

Use this when the paused canary has been manually verified.

```bash
kubectl argo rollouts promote demo-api -n startup-apps
```

## Inspect Rollout History

```bash
kubectl argo rollouts history demo-api -n startup-apps
```

## Roll Back Through GitOps

The preferred GitOps rollback method is to revert the Git commit that changed the Helm values or image tag.

```bash
git revert <commit-sha>
git push
```

Argo CD will reconcile the desired state back into the cluster.

## Local Image Reminder

The kind workflow uses `imagePullPolicy: Never`.

Before syncing a new image tag, build and load it into kind:

```bash
docker build -t startup-devops-baseline/demo-api:0.1.1 apps/demo-api
kind load docker-image startup-devops-baseline/demo-api:0.1.1 --name startup-devops-baseline
```
