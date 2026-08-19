# AWS Progressive Delivery

## Scope

v0.9.5 declares ALB-based Argo Rollouts for aws-test and aws-prod. It does not
create either cluster. aws-dev remains the existing Deployment baseline so the
increment does not change its already validated runtime behavior.

The target path is:

```text
reviewed release PR
  -> target Argo CD sync
  -> Argo Rollout creates canary ReplicaSet
  -> ALB weights stable/canary target groups
  -> canary Web AnalysisRun checks /ready and /version
  -> manual progression gate
  -> 100% stable completion
  -> local runtime evidence PR
```

## GitOps Components

`clusters/aws/base/platform/argo-rollouts.yaml` installs the same pinned Argo
Rollouts chart used by the local environment. The shared demo-api Application
lets Rollouts own only these mutable fields:

- stable and canary Service selectors;
- `alb.ingress.kubernetes.io/actions.demo-api-stable`;
- `rollouts.argoproj.io/managed-alb-actions`.

Argo CD continues to own every other field and uses
`RespectIgnoreDifferences=true` so self-heal does not fight the rollout
controller.

The Ingress backend points to `demo-api-stable` with port name
`use-annotation`. Argo Rollouts injects the ALB forward action and changes its
stable/canary weights at each `setWeight` step. No service mesh is introduced.

## Environment Policies

| Environment | Workload | Progression |
|---|---|---|
| aws-dev | Deployment | Existing direct rolling update |
| aws-test | Rollout | 20%, 60s pause, AnalysisRun, 50%, manual gate, 100% |
| aws-prod | Rollout | 10%, 5m pause, AnalysisRun, 25%, manual gate, 50%, 10m pause, 100% |

Both Rollouts set `maxSurge: 1` and `maxUnavailable: 0`. Production uses the
slower progression and longer progress deadline. The GitHub `aws-prod`
Environment approval protects creation of the release PR; the manual Rollout
pause remains a separate live-traffic decision after that PR is reviewed,
merged, and reconciled.

## Analysis Boundary

The AWS AnalysisTemplate uses the Argo Rollouts Web provider against the
canary-only Service:

- `/ready` must report application readiness and `database: ok`;
- `/version` must report the expected environment and promoted application
  version.

The AnalysisRun also stores the image digest and source commit as arguments.
The runtime collector requires a Successful AnalysisRun whose four identity
arguments match the current release. This provides a release-bound canary
check without deploying the full Prometheus/Grafana/Alertmanager platform
planned for v0.11.

The startup-apps default-deny policy permits this check only from Pods labeled
as the Argo Rollouts controller in the `argo-rollouts` namespace, and only to
demo-api TCP port 8080. ALB ingress and database egress retain their existing
independent allow rules.

## Live Operation

After the target release PR is merged and Argo CD starts a Rollout:

```bash
kubectl argo rollouts get rollout demo-api -n startup-apps --watch
```

At the indefinite pause, inspect the Rollout, AnalysisRun, public endpoint, and
ALB action. Promote only after those checks are satisfactory:

```bash
kubectl argo rollouts promote demo-api -n startup-apps
kubectl argo rollouts status demo-api -n startup-apps --timeout 15m
```

Abort a failing release without modifying Git:

```bash
kubectl argo rollouts abort demo-api -n startup-apps
```

Then use the governed GitOps rollback workflow to make the stable desired state
durable. An imperative abort is incident containment, not the final Git record.

## Runtime Evidence

Collect evidence only after the source environment is fully converged:

```bash
git switch main
git pull --ff-only

ENVIRONMENT=aws-test \
EVIDENCE_ACTOR=SterlingAureum \
./scripts/record-demo-api-runtime-evidence-aws.sh
```

The script requires a clean `main` equal to `origin/main`, updates kubeconfig
for the selected environment, and validates:

- Argo CD `Synced` and `Healthy` at the exact repository revision;
- workload and Pod delivery annotations;
- every selected Pod ready and using the exact digest;
- HTTPS health, database readiness, environment, and application version;
- for aws-test/aws-prod, Healthy completed Rollout, matching Successful
  AnalysisRun, and a 100%-stable ALB action.

It writes only:

```text
evidence/demo-api/runtime/<environment>/<UTC-YYYYMMDDHHMMSS>.json
```

Review that JSON, then create an evidence-only branch and PR:

```bash
git switch -c evidence/demo-api-aws-test-runtime-<evidence-id>
git add evidence/demo-api/runtime/aws-test/<evidence-id>.json
git diff --cached --name-only
git commit -m "evidence: record aws-test demo-api runtime"
git push -u origin HEAD
gh pr create --base main --fill
```

Merge it through CODEOWNERS. Then supply both `evidence_run_id` and
`runtime_evidence_id` to the ordered promotion workflow. Runtime evidence
expires after 72 hours by default and becomes invalid immediately if the
source release file changes.

## v0.9.5 Acceptance Boundary

This increment is complete when Helm/YAML/static behavior gates pass and the
repository contains the progressive-delivery and evidence mechanisms. It does
not claim live aws-test or aws-prod success. v0.9.6 performs the clean-room
dev/test sequence, optional production static validation, evidence capture,
teardown, billable-resource checks, and final documentation.
