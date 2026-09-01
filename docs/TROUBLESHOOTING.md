# Troubleshooting

## info58-60: monitoring OutOfSync and system Pod-slot exhaustion

Two t3.medium system nodes each had 17/17 Pods. Operator and node-exporter
could not schedule; resource request percentages did not reveal the Pod limit.
Grafana random credentials caused a separate Secret/checksum diff. See
`V0.11.8.1.4_SYSTEM_CAPACITY_GRAFANA_REPAIR.md` for independent credential
preparation, guarded expansion and per-node relocation/readiness acceptance.

## info57: first dev deployment fails with ResourceNotFoundException

v0.11.8.1.3 separates initial creation (`apply-aws-dev.sh`) from endpoint
maintenance. Previously the deployment guide called maintenance, whose logging
preservation requires an existing cluster. Check account/region first; see
`V0.11.8.1.3_AWS_DEPLOYMENT_ENTRYPOINT_REPAIR.md` for the guarded creation flow.

## aws-dev Root and child Applications use a split revision

Symptom: the aws-dev Root Application is deployed from the feature branch, but
same-repository child Applications still report `spec.source.targetRevision:
main`. The Root revision selects only the overlay that creates the children; it
does not automatically rewrite each child's source revision.

Apply v0.11.8.1.2, render the revision boundary, and reconcile aws-dev. The dev
overlay replaces the source revision for exactly nine same-repository child
Applications. External Helm Charts, aws-test, and aws-prod remain pinned.

Before merging to main, remove the dev-only feature patch, require all three
AWS overlays to render same-repository children from `main`, and rerun the
complete quality gate. This is a pre-merge qualification bridge, not a stable
branch policy.

## `Workflow gained AWS/EKS runtime access`

If the reported file is `aws-dev-observability-qualification.yaml` on an
unrepaired v0.11.8.1 checkout, the historical release-orchestration scanner has
not recognized its successor contract. This is a local static-validator
compatibility failure, not an AWS connection failure and not a reason to merge
or switch to main. Apply v0.11.8.1.1 and rerun the same complete quality gate.
Every other newly introduced AWS/EKS workflow remains rejected. See
`V0.11.8.1.1_OBSERVABILITY_WORKFLOW_BOUNDARY_SUCCESSOR_REPAIR.md`.

## Environment Qualification Reports `waiting-runtime`

`waiting-runtime` means that the selected local or AWS runtime was absent or
unreachable before any capability could be verified. It is a resumable state,
not a passing qualification and not evidence that a capability is deployed.
Do not create, synchronize, promote, or mutate an environment from a v0.11.8
qualification checker. Confirm the intended account, region, cluster, context,
immutable target revision, and exact application version, then resume through
the environment-specific Runbook. See
`V0.11.8.0_ENVIRONMENT_OBSERVABILITY_QUALIFICATION_FOUNDATION.md`.

For an aws-dev `failed` result, inspect the evidence diagnostic before changing
runtime state. A successful result uses reason `aws_dev_observability_qualified`.
Revision mismatch means the Git-sourced Applications have not reconciled the
exact protected-main commit; Chart mismatch is checked separately against
kube-prometheus-stack `88.5.0`. See
`V0.11.8.1_AWS_DEV_LIVE_OBSERVABILITY_QUALIFICATION.md`.

For the closed local SLO/progressive-delivery sequence and its incident index,
see `V0.11.7.3_LOCAL_SLO_PROGRESSIVE_DELIVERY_CLOSURE.md`. The retained cases
cover Git/application identity confusion, provider-side PromQL parsing, stale
canary Endpoint identity, and pre-scrape counter traffic.
Final status convergence after the second AnalysisRun is documented in
`V0.11.7.3.1_FINAL_ROLLOUT_CONVERGENCE_WAIT_TROUBLESHOOTING.md`.

This document records common issues observed while building and validating the v0.1 local GitOps baseline.

## kube-proxy CrashLoopBackOff: too many open files

Symptom:

```text
kube-proxy CrashLoopBackOff
failed complete: too many open files
```

Possible cause:

The local Docker daemon or Docker networking state may be unhealthy. In the observed case, the kind node container had a high `ulimit -n`, but kube-proxy still failed until Docker was restarted.

Checks:

```bash
kubectl get pods -n kube-system
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=100
docker exec startup-devops-baseline-control-plane sh -c "ulimit -n"
```

Suggested fix:

```bash
sudo systemctl restart docker
```

Then recreate or recheck the kind cluster.

## Argo CD CRD Annotation Too Long

Symptom:

```text
The CustomResourceDefinition "applicationsets.argoproj.io" is invalid:
metadata.annotations: Too long: must have at most 262144 bytes
```

Cause:

Client-side `kubectl apply` stores large manifests in the `kubectl.kubernetes.io/last-applied-configuration` annotation. Some Argo CD CRDs are too large for this limit.

Fix:

Use server-side apply:

```bash
kubectl apply --server-side --force-conflicts \
  -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

The repository install script should already use server-side apply.

## startup-devops-root Application Is Missing

Symptom:

```bash
kubectl get applications -n argocd
```

does not show:

```text
startup-devops-root
```

Cause:

The Application is not created by installing Argo CD. It is created by:

```bash
./scripts/deploy-root-app.sh
```

If the cluster or Argo CD namespace was recreated, the Application must be recreated.

Fix:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

## Root Is OutOfSync During Feature Validation

Symptoms:

- `startup-devops-root` is `OutOfSync / Healthy`;
- `demo-api` is synced to a feature revision;
- syncing the Root changes `demo-api` back to `HEAD`;
- the deployed Chart or ServiceMonitor unexpectedly returns to the mainline
  version.

Cause:

This is the pre-v0.11.3.4 model: live child revisions were patched away from
the Root's tracked `HEAD` declarations. A Root sync correctly restored its own
desired state and therefore reset the children.

Fix:

Use the v0.11.3.4 unified workflow:

```bash
TARGET_REVISION=feature/v0.11-observability-sre-baseline \
IMAGE_TAG=v0.11.3-local \
  ./scripts/deploy-local-feature-gitops.sh
```

The branch is resolved to one full commit SHA and rendered by the Root into
both same-repository children. Root and children must remain `Synced`; a Root
resync is now safe. If Root remains `OutOfSync`, confirm that the platform path
contains `Chart.yaml`, that no legacy raw Application YAML remains beside it,
and that Root carries the `git.targetRevision` Helm parameter.

Before merge, restore the clean feature baseline afterward:

```bash
TARGET_REVISION=feature/v0.11-observability-sre-baseline \
  ./scripts/restore-local-feature-baseline.sh
```

Use `./scripts/restore-local-gitops-head.sh` only after the platform Chart has
reached remote HEAD.

## Root Helm Source Reports Chart.yaml Does Not Exist

Symptoms:

- Root uses `spec.source.helm`;
- Root targets `HEAD`;
- Argo CD reports `clusters/local/platform/Chart.yaml: no such file or directory`;
- child Applications may appear with `requiresPruning: true`.

Cause:

The live Root has already adopted the new Helm source shape while remote HEAD
still points to a pre-migration directory source. The cached comparison error
is evidence of a real Git content mismatch, not a cache defect.

Fix:

Do not prune or delete the child Applications. Commit and push the repair to
the feature branch, then restore the immutable feature baseline:

```bash
TARGET_REVISION=feature/v0.11-observability-sre-baseline \
  ./scripts/restore-local-feature-baseline.sh
```

The v0.11.3.5 Root source preflight rejects a revision that lacks the platform
Chart before contacting Kubernetes. HEAD restoration becomes valid only after
that Chart reaches remote HEAD.

If `demo-api` is `Suspended`, inspect the latest AnalysisRun. Promote normally
only after it is `Successful`; never use full promotion to hide a failed gate.

## Argo CD Reports Another Operation Is Already in Progress

Cause:

An automated Application operation may still be running when a manual sync is
requested. In older local feature flows, applying the automated Root and then
patching it to manual mode left a race window. Even after that creation race
was removed, the Argo CD API's server-side operation lock may briefly outlive
the idle state visible in the Application custom resource.

Fix:

Use the v0.11.3.3 scripts. Manual mode is rendered before apply, and `sync`,
`set`, and `unset` retry only the exact operation-busy failure with a bounded
wait. Do not run a second manual sync concurrently and do not terminate a valid
operation to force acceptance.

Inspect a persistent failure with:

```bash
kubectl -n argocd get application startup-devops-root \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase,MESSAGE:.status.operationState.message'
```

If the five-attempt bound is exhausted, preserve the output and diagnose the
operation instead of increasing the retry count without evidence.

## AnalysisTemplate Keeps an Old Prometheus Address

Cause:

A live `spec.source.helm.parameters` entry such as
`analysis.prometheus.address` survived from an earlier manual override. A Root
sync does not reliably delete a child Helm parameter that its Git manifest
does not declare.

Fix:

Rerun `deploy-local-feature-gitops.sh`. The Root declaratively renders only the
four local-image parameters. The applicable feature or HEAD baseline restore
renders `parameters: []` and asserts an empty live set without direct child
`set` or `unset` operations.

For an actually aborted Rollout, the retry syntax includes the resource type:

```bash
kubectl argo rollouts retry rollout demo-api -n startup-apps
```

## AnalysisRun Reports reflect: slice index out of range

Symptoms:

- the Prometheus address and resolved query are correct;
- `ServiceMonitor/demo-api` was recently created;
- the metric records repeated `reflect: slice index out of range` errors;
- the Rollout aborts after the consecutive error limit.

Cause:

Prometheus returned an empty vector before the new Canary target produced a
sample, and an older AnalysisTemplate evaluated `result[0]` without checking
the vector length.

Fix:

Use Chart `0.5.1` or later. The metric waits before its first measurement and
uses `len(result) > 0 && result[0] >= 1`, so no-data fails closed without an
expression Error. Do not use full promotion. Preserve the failed AnalysisRun,
apply the fix through Git, restore the applicable pre-merge feature or
post-merge HEAD baseline, and perform a new clean feature replay.

## Argo CD Cannot Pull Repository

Symptoms:

- Application is `OutOfSync` or `Unknown`.
- Application events mention repository access failures.
- Child applications are not created.

Checks:

```bash
kubectl describe application startup-devops-root -n argocd
kubectl logs -n argocd deploy/argocd-repo-server --tail=100
```

Fixes:

- Confirm `REPO_URL` is correct.
- Confirm changes are pushed to GitHub.
- Use a public repository for local demo, or configure repository credentials in Argo CD.

## demo-api Pod Is ImagePullBackOff

Cause:

The image may not have been loaded into the kind cluster.

Fix:

```bash
./scripts/build-load-demo-api-image.sh
kubectl rollout restart deploy/demo-api -n startup-apps
```

Check:

```bash
kubectl get pods -n startup-apps
kubectl describe pod -n startup-apps -l app.kubernetes.io/name=demo-api
```

## Ingress Does Not Work

Checks:

```bash
kubectl get pods -n ingress-nginx
kubectl get ingress -n startup-apps
kubectl get svc -n startup-apps
curl -H "Host: demo-api.local" http://localhost/health
```

If the Host header works but the hostname does not, add:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
```

## Prometheus Port 9090 Already in Use

Symptom:

```text
Unable to listen on port 9090: bind: address already in use
```

Cause:

Another local Prometheus or service is already listening on port 9090.

Check:

```bash
sudo ss -ltnp | grep ':9090'
docker ps | grep 9090
```

Fix:

Use a different local port:

```bash
kubectl -n observability port-forward \
  svc/observability-metrics-prometheus 19090:9090
```

The optimized `validate.sh` automatically finds a free local port for Prometheus checks.

## Prometheus Query Succeeds but demo-api Metric Is Missing

Cause:

Prometheus may not have scraped demo-api yet, the application-owned
ServiceMonitor may not be reconciled, or there has been no recent traffic.

Check discovery:

```bash
kubectl -n startup-apps get servicemonitor demo-api
kubectl -n observability get prometheus
```

Generate traffic:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

Wait for the next scrape interval and query again.

The active metric name is `demo_api_http_requests_total`. If only
`demo_api_requests_total` is present, the running image is older than v0.11.2.

For a complete target, identity-label, application-metric, and platform-metric
check, run:

```bash
./scripts/check-monitoring.sh
```

## Full Validation

Run:

```bash
./scripts/validate.sh
```

If Prometheus HTTP validation is not needed:

```bash
SKIP_PROMETHEUS_HTTP=true ./scripts/validate.sh
```
