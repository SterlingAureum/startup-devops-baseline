# Multi-Environment Release Runbook

This is the canonical operator procedure for moving one immutable demo-api
image through the v0.9 release chain:

```text
build -> aws-dev -> aws-test -> aws-prod
```

Use this document when executing or reviewing a release. Architecture and
policy rationale remain in `MULTI_ENVIRONMENT_GITOPS_MODEL.md` and
`PROMOTION_GOVERNANCE.md`; infrastructure creation and teardown remain in
`AWS_MULTI_ENVIRONMENT_LIFECYCLE.md`.

The v0.9 production acceptance boundary is deliberately static. Updating the
aws-prod release file on `main` proves the GitOps governance path. It does not
claim an aws-prod cluster, Argo CD sync, Rollout, ALB traffic shift, or live
production runtime validation unless those resources separately exist and are
validated.

## 1. Release invariants

- Run every workflow from `main` and every local evidence command from a clean
  local `main` exactly equal to `origin/main`.
- Build once. Promotion copies the complete image and delivery identity; it
  never rebuilds or retags the image.
- Each evidence PR must be merged into `main` before its ID is supplied to a
  Promotion workflow.
- A Promotion PR changes exactly one target release file beneath
  `apps/demo-api/helm/values/releases/`.
- GitHub Actions prepares branches and PRs but never merges them and never
  receives AWS, EKS, Kubernetes, or Argo CD credentials.
- Human review remains mandatory for evidence and release changes. Production
  approval remains a human risk decision.
- Runtime evidence defaults to 72 hours of validity. Static qualification
  evidence defaults to seven days. Either record becomes unusable immediately
  when the source release file no longer matches its recorded SHA-256.

## 2. One-time GitHub configuration

Repository files describe the intended governance, but the following GitHub
settings make it enforceable.

### 2.1 Actions permissions

Open **Settings -> Actions -> General -> Workflow permissions** and configure:

- **Read and write permissions**;
- **Allow GitHub Actions to create and approve pull requests** enabled.

The workflows request narrower job-level permissions, and none of them call a
PR approval or merge command. The second repository setting is nevertheless
required for `GITHUB_TOKEN` to create evidence and Promotion PRs.

Reference: <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository>

### 2.2 Environments

Open **Settings -> Environments** and create these exact repository names:

```text
aws-dev
aws-test
aws-prod
```

Recommended protection:

| Environment | Required reviewer | Prevent self-review | Allowed branch |
|---|---|---|---|
| `aws-dev` | Optional | Optional | `main` |
| `aws-test` | Optional or test/platform reviewer | When a second reviewer exists | `main` |
| `aws-prod` | Required production/platform reviewer | Yes for a real team | `main` |

For a single-maintainer portfolio repository, do not enable **Prevent
self-review** with the triggering maintainer as the only possible reviewer;
that configuration cannot be approved. Either use a distinct reviewer or
document the portfolio limitation. A real production repository should use a
reviewer other than the workflow initiator and prevent self-review.

No AWS, kubeconfig, or Kubernetes secret is required in these Environments.
The jobs use `deployment: false` because they prepare Git evidence or release
PRs rather than deploying directly.

Reference: <https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments>

### 2.3 Main protection and CODEOWNERS

Protect `main` with a branch protection rule or ruleset that requires:

- changes through pull requests;
- at least one approval appropriate for the repository;
- review from Code Owners;
- the successful quality-gate check produced by the `validate` workflow.

Require the successful check produced by `terraform validate` as well when
Terraform paths are changed. Select the exact check names shown by a completed
pull request because GitHub's displayed names include workflow/job nesting.
Keep `.github/CODEOWNERS` protected and replace the portfolio owner with real
platform and production-approval teams in an organizational use.

References:

- <https://docs.github.com/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>
- <https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule>

## 3. Operator prerequisites

The full live procedure uses:

```text
git  gh  aws  curl  jq  kubectl  helm  python3  terraform
```

Authenticate and establish a clean source state:

```bash
gh auth status
aws sts get-caller-identity

git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

`git status --short` must be empty and the two revisions must match. Set the
operator identity once for the shell session:

```bash
export EVIDENCE_ACTOR="$(gh api user --jq .login)"
```

Before a local runtime-evidence step, also confirm:

- the source cluster exists and is healthy;
- the current public egress `/32` is allowed by its EKS endpoint;
- the expected DNS name resolves and HTTPS is reachable;
- the Argo CD Application tracks `main`.

If a VPN or public address changed, update only the selected live environment:

```bash
AWS_ENVIRONMENT=aws-dev \
CONFIRM_EKS_API_CIDR_UPDATE=restrict-current-ip \
  ./scripts/apply-eks-api-access-cidr.sh
```

Use `AWS_ENVIRONMENT=aws-test` for test. The updater preserves the current EKS
control-plane logging profile and does not write the public address to Git.

Run the static preflight:

```bash
./scripts/validate-aws-environment-declarations.sh
./scripts/validate-demo-api-aws-progressive-delivery.sh
./scripts/validate-v0.9-lifecycle-contracts.sh
./scripts/validate-ci-quality-gates.sh
```

Use this review pattern for every generated evidence or release PR:

```bash
gh pr list --state open --base main --limit 20
gh pr view <pr-number>
gh pr diff <pr-number> --name-only
gh pr diff <pr-number>
gh pr checks <pr-number> --watch
```

Merge only after the expected reviewer and required checks pass. If repository
policy allows command-line merge, the final action is:

```bash
gh pr merge <pr-number> --merge --delete-branch
```

Using GitHub's web review and merge controls is equally valid and is required
when the current operator is not the eligible reviewer.

## 4. Publish once and update aws-dev

An accepted demo-api source change on `main` automatically starts
`demo-api-image-publish.yaml`. To publish the current `main` manually and ask
the same workflow to create the aws-dev release PR, run:

```bash
gh workflow run demo-api-image-publish.yaml \
  --ref main \
  -f create_promotion_pr=true \
  -f promotion_base_branch=main
```

Find and follow the run:

```bash
gh run list \
  --workflow demo-api-image-publish.yaml \
  --branch main \
  --limit 5

gh run watch <image-publish-run-id> --exit-status
gh run view <image-publish-run-id>
```

The workflow builds, scans, publishes, and attests the image, then creates a PR
whose only release mutation is:

```text
apps/demo-api/helm/values/releases/aws-dev.yaml
```

Review the SHA tag, digest, source commit, workflow run ID, and changed-file
list. Merge the PR, update local `main`, and wait for the aws-dev Argo CD
Application to become Synced and Healthy:

```bash
git switch main
git pull --ff-only origin main

aws eks update-kubeconfig \
  --region us-east-1 \
  --name startup-devops-baseline-dev

kubectl -n argocd get application demo-api-aws-dev
kubectl -n startup-apps rollout status deployment/demo-api --timeout=10m
curl --fail --silent --show-error \
  https://demo.dev.aureumstack.com/version | jq .
```

Do not continue if the live version, release annotations, or Pod image digest
does not match the merged aws-dev release file.

## 5. Collect and merge runtime evidence

Static qualification and runtime evidence may be collected in either order,
but both PRs must be reviewed and merged before Promotion. This runbook records
runtime evidence first so the live state is captured as soon as it is accepted.

Set the source environment and a UTC evidence ID explicitly:

```bash
export SOURCE_ENVIRONMENT=aws-dev
export RUNTIME_EVIDENCE_ID="$(date -u +%Y%m%d%H%M%S)"

ENVIRONMENT="${SOURCE_ENVIRONMENT}" \
EVIDENCE_ACTOR="${EVIDENCE_ACTOR}" \
EVIDENCE_ID="${RUNTIME_EVIDENCE_ID}" \
  ./scripts/record-demo-api-runtime-evidence-aws.sh
```

The generated path is:

```text
evidence/demo-api/runtime/<source-environment>/<runtime-evidence-id>.json
```

Review and submit only that record:

```bash
git switch -c \
  "evidence/${SOURCE_ENVIRONMENT}-runtime-${RUNTIME_EVIDENCE_ID}"
git add \
  "evidence/demo-api/runtime/${SOURCE_ENVIRONMENT}/${RUNTIME_EVIDENCE_ID}.json"
git diff --cached --name-only
git diff --cached
git commit -m "evidence: record ${SOURCE_ENVIRONMENT} demo-api runtime"
git push -u origin HEAD
gh pr create --base main --fill
```

The staged path list must contain exactly one runtime JSON record. Review and
merge the PR, then return to the current `main`:

```bash
git switch main
git pull --ff-only origin main
```

Keep `RUNTIME_EVIDENCE_ID`; it is the 14-digit UTC filename without `.json`,
not a GitHub Actions run number.

## 6. Create and merge qualification evidence

Dispatch the qualification workflow for the same source environment:

```bash
gh workflow run demo-api-record-release-evidence.yaml \
  --ref main \
  -f environment="${SOURCE_ENVIRONMENT}"

gh run list \
  --workflow demo-api-record-release-evidence.yaml \
  --branch main \
  --event workflow_dispatch \
  --limit 5
```

Copy the numeric **database ID** of the new run and watch it:

```bash
export EVIDENCE_RUN_ID=<qualification-workflow-run-id>

gh run watch "${EVIDENCE_RUN_ID}" --exit-status
gh run view "${EVIDENCE_RUN_ID}"
```

The workflow enters the source GitHub Environment, lints and renders the Helm
profile, validates the release record, proves the exact GHCR digest exists,
and creates an evidence-only PR containing:

```text
evidence/demo-api/<source-environment>/<evidence-run-id>.json
```

Review and merge that PR. Confirm both records now exist on `main`:

```bash
git switch main
git pull --ff-only origin main

test -f \
  "evidence/demo-api/${SOURCE_ENVIRONMENT}/${EVIDENCE_RUN_ID}.json"
test -f \
  "evidence/demo-api/runtime/${SOURCE_ENVIRONMENT}/${RUNTIME_EVIDENCE_ID}.json"
```

`EVIDENCE_RUN_ID` is the GitHub qualification workflow run ID.
`RUNTIME_EVIDENCE_ID` is the local UTC timestamp. They are not interchangeable.

## 7. Prepare the target environment

For `aws-dev -> aws-test`, create and bootstrap the temporary test environment
before merging the target release PR. Skip this section only when the existing
aws-test cluster was created from the current reviewed `main`.

```bash
CONFIRM_AWS_TEST_APPLY=apply-ephemeral-aws-test \
  ./scripts/apply-aws-test.sh

CONFIRM_AWS_TEST_BOOTSTRAP=bootstrap-ephemeral-aws-test \
  ./scripts/bootstrap-aws-test.sh
```

If Terraform apply was interrupted after creating resources, inspect its state
and resume the same environment:

```bash
AWS_TEST_APPLY_MODE=resume \
CONFIRM_AWS_TEST_APPLY=apply-ephemeral-aws-test \
  ./scripts/apply-aws-test.sh
```

Do not delete Terraform state or create a differently named replacement.

For the v0.9 `aws-test -> aws-prod` static acceptance, no aws-prod cluster is
created. The target release PR represents desired state only.

## 8. Promote aws-dev to aws-test

With `SOURCE_ENVIRONMENT=aws-dev`, dispatch the only allowed next edge:

```bash
gh workflow run demo-api-promote-environment.yaml \
  --ref main \
  -f source_environment=aws-dev \
  -f target_environment=aws-test \
  -f evidence_run_id="${EVIDENCE_RUN_ID}" \
  -f runtime_evidence_id="${RUNTIME_EVIDENCE_ID}"

gh run list \
  --workflow demo-api-promote-environment.yaml \
  --branch main \
  --event workflow_dispatch \
  --limit 5
```

Approve the `aws-test` Environment job if that Environment has protection.
The workflow must create a PR that changes only:

```text
apps/demo-api/helm/values/releases/aws-test.yaml
```

Review and merge it. The workflow itself does not access EKS and does not merge
the PR. Argo CD starts the test Rollout only after the merge reaches `main`.

## 9. Complete and validate the aws-test Rollout

```bash
git switch main
git pull --ff-only origin main

aws eks update-kubeconfig \
  --region us-east-1 \
  --name startup-devops-baseline-test

./scripts/rollout-status.sh
kubectl -n startup-apps get rollout demo-api
kubectl -n startup-apps get analysisrun
```

Review the current canary, live image, readiness, database path, expected
version, ALB routing, and AnalysisRun before authorizing the explicit manual
pause. The helper advances only explicit indefinite pauses and refuses more
than three of them:

```bash
CONFIRM_AWS_TEST_ROLLOUT=promote-reviewed-aws-test \
  ./scripts/complete-aws-test-rollout.sh
```

Then validate the complete test runtime and record its evidence:

```bash
export SOURCE_ENVIRONMENT=aws-test
export RUNTIME_EVIDENCE_ID="$(date -u +%Y%m%d%H%M%S)"

EVIDENCE_ACTOR="${EVIDENCE_ACTOR}" \
EVIDENCE_ID="${RUNTIME_EVIDENCE_ID}" \
  ./scripts/validate-aws-test-runtime.sh
```

`validate-aws-test-runtime.sh` passes `EVIDENCE_ID` through to the runtime
collector when `EVIDENCE_ACTOR` is set. Submit the generated aws-test runtime
JSON through the evidence-only branch and PR procedure in section 5, then
merge it.

If an AnalysisRun fails, inspect and abort or roll back. Do not force a failed
analysis forward:

```bash
./scripts/rollout-abort.sh
```

## 10. Qualify aws-test

Repeat the qualification procedure for the current test release:

```bash
gh workflow run demo-api-record-release-evidence.yaml \
  --ref main \
  -f environment=aws-test

gh run list \
  --workflow demo-api-record-release-evidence.yaml \
  --branch main \
  --event workflow_dispatch \
  --limit 5
```

Set `EVIDENCE_RUN_ID` to that new workflow run ID, wait for success, review and
merge the generated aws-test qualification-evidence PR, then update local
`main`.

At this point, both test evidence records are on `main`:

```text
evidence/demo-api/aws-test/<evidence-run-id>.json
evidence/demo-api/runtime/aws-test/<runtime-evidence-id>.json
```

## 11. Optional cost-saving pause and aws-test destroy

After the aws-test runtime evidence has been generated, reviewed, and merged,
the cluster is no longer required for the static `aws-test -> aws-prod`
Promotion workflow. Qualification also runs entirely in GitHub Actions.

Destroy the temporary environment when the live work is complete:

```bash
CONFIRM_AWS_ENVIRONMENT_DESTROY=destroy-aws-test-with-backups \
  ./scripts/destroy-aws-test.sh

AWS_ENVIRONMENT=aws-test \
  ./scripts/validate-aws-cost-cleanup.sh
```

The evidence remains usable after cluster destruction only while all of these
conditions remain true:

- its evidence-only PR is merged into `main`;
- the recorded source release file is unchanged;
- runtime evidence is no more than 72 hours old;
- static qualification evidence is no more than seven days old.

If only the cluster was destroyed and these conditions still hold, do not
rebuild dev or test merely to continue the static production Promotion. If the
test release changed or runtime evidence expired, rebuild aws-test from current
`main`, complete its Rollout, and collect a new runtime record. aws-dev still
does not need rebuilding unless the dev source release itself must be
re-qualified for another dev-to-test Promotion.

## 12. Promote aws-test to aws-prod

With the new aws-test IDs set, dispatch:

```bash
gh workflow run demo-api-promote-environment.yaml \
  --ref main \
  -f source_environment=aws-test \
  -f target_environment=aws-prod \
  -f evidence_run_id="${EVIDENCE_RUN_ID}" \
  -f runtime_evidence_id="${RUNTIME_EVIDENCE_ID}"

gh run list \
  --workflow demo-api-promote-environment.yaml \
  --branch main \
  --event workflow_dispatch \
  --limit 5
```

Approve the `aws-prod` Environment gate through the designated reviewer. The
resulting PR must change only:

```text
apps/demo-api/helm/values/releases/aws-prod.yaml
```

Review the source/test evidence paths, immutable digest, source commit, and
changed-file list. Merge the PR through CODEOWNERS. In the v0.9 cost-aware
acceptance, this completes the production GitOps governance path without
claiming a live production deployment.

Confirm the final desired-state identity:

```bash
git switch main
git pull --ff-only origin main

git diff HEAD^ HEAD -- \
  apps/demo-api/helm/values/releases/aws-prod.yaml

diff -u \
  apps/demo-api/helm/values/releases/aws-test.yaml \
  apps/demo-api/helm/values/releases/aws-prod.yaml
```

The final `diff -u` should be empty when the complete test release identity was
copied without mutation.

## 13. Safe pause and resume points

| Pause point | Safe state | Resume action |
|---|---|---|
| Image workflow succeeded; aws-dev PR open | No desired-state change yet | Review and merge the existing PR |
| aws-dev PR merged | Dev desired state is durable on `main` | Wait for Argo CD, then collect evidence |
| Runtime evidence generated but not merged | Evidence is only local | Submit and merge its one-file PR before destroying the cluster |
| Both source evidence PRs merged | Promotion inputs are durable and time-bounded | Dispatch Promotion using their two distinct IDs |
| dev-to-test PR merged; Rollout paused | Test rollout is intentionally incomplete | Review live state, then run the guarded completion helper |
| Test evidence merged; test destroyed | Static production Promotion may continue | Check age and release SHA binding, then dispatch test-to-prod |
| Production workflow waiting | No prod release PR exists yet | Designated reviewer approves the `aws-prod` Environment job |
| Prod release PR merged | v0.9 static governance is complete | Record acceptance boundary; do not claim live prod runtime |

Never leave a temporary test cluster running merely because the next action is
a GitHub review. Record and merge the required live evidence first, then use
the dependency-aware destroy and cleanup audit.

## 14. Troubleshooting

### Workflow cannot create a PR

Enable **Settings -> Actions -> General -> Workflow permissions -> Allow
GitHub Actions to create and approve pull requests**, then rerun the failed
workflow. Do not manually widen workflow credentials beyond its declared
permissions.

### `evidence_run_id` and `runtime_evidence_id` were confused

- `evidence_run_id`: numeric GitHub Actions run ID; path is
  `evidence/demo-api/<environment>/<run-id>.json`.
- `runtime_evidence_id`: 14-digit UTC timestamp; path is
  `evidence/demo-api/runtime/<environment>/<timestamp>.json`.

The workflow input is exactly `evidence_run_id`. The legacy name
`release_evidence_run_id` is invalid.

### Evidence file is missing from `main`

The evidence workflow or local collector only prepares a record. Its PR must
be reviewed and merged before Promotion. Update local `main` and verify both
paths with `test -f`.

### Evidence expired or source release drifted

Do not edit the JSON. Generate and merge new evidence for the current source
release. Runtime evidence requires the live source environment; static
qualification does not.

### `main changed while promotion was being prepared`

The stale-main guard failed closed. Pull current `main`, confirm the source
release and both evidence records still match, then rerun the workflow. If the
source release changed, create fresh evidence instead of reusing old IDs.

### Workflow waits for Environment approval

Open the workflow run and review the pending environment. Confirm the exact
Environment exists and has an eligible reviewer. In a single-maintainer repo,
`Prevent self-review` plus no second reviewer creates an intentional deadlock;
fix the reviewer model rather than bypassing an approved production policy.

### CODEOWNERS review is not required

Confirm `.github/CODEOWNERS` covers the changed path and that the `main`
protection rule or ruleset enables **Require review from Code Owners**.
CODEOWNERS alone requests a reviewer but does not make that review mandatory.

### EKS API returns timeout, EOF, or authorization discovery errors

Confirm the current VPN/public egress address, update the selected environment
through `apply-eks-api-access-cidr.sh`, refresh kubeconfig, and verify the
context contains the expected cluster name. Never commit the address or widen
the endpoint to `0.0.0.0/0`.

### Argo CD or Rollout does not converge

Confirm the target release PR is merged into `main`, the Application tracks
`main`, its observed revision equals the intended commit, the exact image
digest exists, and the AnalysisRun status. Abort or use the governed rollback
path if analysis fails; do not create runtime evidence from an incomplete
Rollout.

### aws-test was destroyed before test-to-prod

Continue without rebuilding when the test runtime and qualification records
are merged, fresh, and bound to the unchanged test release. Rebuild only when
fresh live test evidence is required.

## 15. Acceptance checklist

```text
[ ] GitHub Actions can create PRs but workflows cannot merge them
[ ] aws-dev, aws-test, and aws-prod Environments exist
[ ] aws-prod has an eligible human approval boundary
[ ] main requires PR and CODEOWNERS review
[ ] immutable image publish workflow succeeded
[ ] aws-dev release-only PR merged
[ ] aws-dev Argo CD/workload runtime converged
[ ] aws-dev runtime-evidence-only PR merged
[ ] aws-dev qualification-evidence-only PR merged
[ ] dev-to-test Promotion PR changed only aws-test release and merged
[ ] aws-test Rollout and matching AnalysisRun completed successfully
[ ] aws-test runtime-evidence-only PR merged
[ ] aws-test qualification-evidence-only PR merged
[ ] test-to-prod workflow passed aws-prod Environment approval
[ ] test-to-prod PR changed only aws-prod release and merged
[ ] aws-prod release identity matches the qualified aws-test identity
[ ] no live aws-prod claim was made without a real prod runtime validation
[ ] temporary aws-test was destroyed when no longer needed
[ ] aws-test residual-cost audit passed
```

## 16. Related documents

- `CI_IMAGE_WORKFLOW.md`: workflow responsibilities and permission boundary.
- `PROMOTION_GOVERNANCE.md`: evidence, approvals, CODEOWNERS, and rollback
  policy.
- `AWS_PROGRESSIVE_DELIVERY.md`: ALB, Rollout, AnalysisRun, and runtime evidence
  semantics.
- `AWS_MULTI_ENVIRONMENT_LIFECYCLE.md`: aws-test creation, recovery drill,
  dependency-aware destroy, and cleanup audit.
- `GITOPS_ROLLBACK.md`: historical desired-state rollback through a new PR.
