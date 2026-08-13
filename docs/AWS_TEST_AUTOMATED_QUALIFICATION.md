# Automated Dev-to-Test Promotion and AWS Test Qualification

v0.10.5 extends the bounded release orchestrator through aws-test while keeping
review, Canary progression, and production as human boundaries. It uses a
merged, fresh aws-dev Qualification Bundle to prepare one release-only
`aws-dev -> aws-test` pull request. It never merges that PR.

## Sequence

```text
fresh aws-dev Qualification Bundle on main
  -> orchestrator validates Bundle path, SHA-256, release, expiry, and dev Scope
  -> reviewed aws-test release-only PR
  -> human review and merge
  -> Argo Rollouts: 20%, pause, AnalysisRun, 50%, manual pause
  -> human runs complete-aws-test-rollout.sh with its confirmation token
  -> manual orchestrator resume with reviewed-and-completed
  -> same-run aws-test static qualification
  -> trusted read-only aws-test runtime qualification
  -> reviewed aws-test Qualification Bundle PR
  -> human review and merge
  -> prod-approval / prepare-prod-promotion, dispatchAuthorized=true
```

## Activation switches

The two operations are independently disabled unless their exact repository
variables are set:

```text
DEMO_API_AWS_TEST_PROMOTION_ENABLED=true
DEMO_API_AWS_TEST_QUALIFICATION_ENABLED=true
```

The first permits only preparation of the aws-test release file PR. It needs no
AWS credentials or cluster access. The second should be enabled only when the
aws-test cluster, `aws-test-runtime` GitHub Environment, isolated OIDC role, and
ephemeral runner labeled `trusted-runtime` and `aws-test` are ready.

Neither switch creates or restores EKS. A missing disposable environment is a
recoverable wait/block and must be restored through the existing operator
Runbook.

## Qualification Bundle Promotion input

The reusable Promotion Workflow retains the v0.9 manual interface, but its
automated invocation uses `qualification-bundle` mode with four immutable
inputs derived from the same orchestration snapshot:

```text
qualification_bundle_path
qualification_bundle_sha256
release_id
control_plane_sha
```

The Workflow rejects mixed legacy and Bundle inputs. Bundle mode permits only
`aws-dev -> aws-test` and proves that:

- the Bundle file is already present on protected `main`;
- its bytes match the snapshot SHA-256;
- it is qualified, unexpired, and bound to the current aws-dev release;
- its source commit, image digest, release-file SHA-256, and Release ID agree;
- the current aws-dev Scope still matches every recorded file hash;
- `main` remains at the captured control-plane SHA until PR preparation ends.

The resulting branch may change only
`apps/demo-api/helm/values/releases/aws-test.yaml`.

## Manual Canary gate

Merging the aws-test release PR does not immediately start trusted runtime
qualification. The planner returns:

```text
phase: test-qualification
status: waiting_review
recommendedAction: review-and-complete-test-canary
dispatchAuthorized: false
```

Review the Rollout and AnalysisRun, then use the existing guarded helper:

```bash
CONFIRM_AWS_TEST_ROLLOUT=promote-reviewed-aws-test \
  ./scripts/complete-aws-test-rollout.sh
```

After the Rollout is fully completed, resume explicitly:

```bash
gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=resume \
  -f release_id=<demo-api-release-id> \
  -f test_rollout_gate=reviewed-and-completed \
  -f policy=reviewed
```

The confirmation input does not substitute for runtime proof. The trusted
executor independently requires a Healthy, fully stable Rollout, a Successful
AnalysisRun carrying the expected environment, digest, and source commit,
ready Pods with matching immutable `imageID`, and passing HTTPS health,
readiness, and version endpoints. A premature or false confirmation fails
closed and cannot promote the Rollout.

## AWS test Qualification Scope and Bundle

`delivery/contracts/demo-api-qualification-scope-aws-test.json` covers the
shared Helm chart, aws-test environment/release values, AWS base Applications,
ExternalSecret, NetworkPolicy, runtime RBAC, and the test overlay. Evidence and
ordinary documentation are excluded, so merging the Bundle PR does not make
the Bundle invalidate itself.

Durable evidence is written to:

```text
evidence/demo-api/qualification/aws-test/<release-id>/<run-id>-<attempt>.json
```

The Bundle embeds the exact Scope file list and hashes, full same-run static and
runtime results, immutable release identity, trusted executor/AWS/Argo/Rollout/
AnalysisRun/Pod/HTTPS facts, and the earlier static/runtime expiry. Any scoped
deployment change or release change makes the prior Bundle unusable.

## Production stop boundary

After the reviewed aws-test Bundle reaches `main`, the planner reports:

```text
phase: prod-approval
status: waiting_review
recommendedAction: prepare-prod-promotion
targetEnvironment: aws-prod
dispatchAuthorized: false
```

v0.10.5 itself contains no job that prepares prod. v0.10.6 adds only the
Environment-approved release-only PR preparation described in
`docs/AWS_PROD_CONTROLLED_PROMOTION.md`; it still provides no prod runtime
access or direct production mutation.

## Offline validation

```bash
./scripts/validate-demo-api-aws-test-orchestration.sh
./scripts/validate-demo-api-qualification-bundle.sh
./scripts/validate-demo-api-release-orchestrator.sh
./scripts/validate-trusted-runtime-executor.sh
./scripts/validate-reusable-delivery-stages.sh
./scripts/validate-release-orchestration-contract.sh
./scripts/validate-ci-quality-gates.sh
terraform fmt -check -recursive
./scripts/validate-aws-environment-declarations.sh
git diff --check
git status --short
```

The complete quality gate requires Docker, Helm, Terraform, jq, and Kustomize
or kubectl. Live Workflow acceptance remains a post-merge clean-room exercise.
