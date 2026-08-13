# Release Failure Recovery

v0.10.7 hardens the demo-api release control plane after dev, test, and
production PR preparation were introduced. Recovery remains fact-derived and
reviewed. No mutable `current-state.json` is added.

## Operation semantics

| Operation | Meaning | May dispatch a stage |
| --- | --- | --- |
| `status` | Recompute and report current durable facts. | Never |
| `resume` | Recompute after a human or external fact changed. | Only the newly derived bounded action |
| `retry` | Start a new attempt for one exact safely retryable failed Attempt. | Only the same recommended action |
| `start` | Treat current protected main as a new source candidate. | Existing v0.10 bounded actions only |

`status` remains read-only even if all repository activation variables are
enabled. `retry` requires the prior orchestrator `run_id`, `run_attempt`, and
Release ID. The previous Attempt must belong to this repository and Release,
have outcome `blocked` or `failed`, and carry retry class
`safe-new-attempt`.

Use a new orchestrator run for retry:

```bash
gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=retry \
  -f release_id=<release-id> \
  -f retry_run_id=<prior-run-id> \
  -f retry_run_attempt=<prior-run-attempt> \
  -f test_rollout_gate=not-reviewed \
  -f policy=reviewed
```

GitHub's partial job re-run is not accepted as a Qualification Bundle recovery
path. Static and runtime qualification must come from the same new workflow run
and attempt.

## Attempt diagnostics

Every successfully derived orchestrator run records a secret-free
`demo-api-orchestration-attempt-<run>-<attempt>` artifact retained for 14 days.
It includes the pre-execution decision, actual stage outcome, stable reason,
retry class, recommended recovery, and optional rollback handoff.

An Attempt is troubleshooting data, not reviewed Promotion evidence. It is not
committed to Git and cannot replace a merged Qualification Bundle.

| Retry class | Meaning | Operator action |
| --- | --- | --- |
| `safe-new-attempt` | The same bounded stage may be tried again. | Run `retry` with the exact Attempt identity. |
| `resume-after-change` | An external fact must change. | Correct or restore it, then run `resume`. |
| `manual-investigation` | Runtime behavior may be unsafe. | Investigate, then retry or use the rollback handoff. |
| `none` | No retry applies. | Follow the derived human or durable-fact action. |

Absent environments remain resumable and are never created automatically.

## Superseded releases

The collector compares a selected Release with the current aws-dev Release and
open aws-dev release PRs. Git source ancestry is authoritative; a higher build
run identifies a newer rebuild only when the source commit is identical.
Unrelated source histories are `release-order-ambiguous` and block execution.

A superseded Release returns:

```text
status: superseded
reason: newer-release-active
recommendedAction: review-and-close-superseded-pr
dispatchAuthorized: false
```

The workflow does not close a PR automatically. Reviewers close obsolete PRs,
and required branch checks must be current before merge.

## Qualification Bundle states

The snapshot classifies a candidate Bundle as:

```text
missing | fresh | expiring | expired | scope_drift | release_drift | invalid
```

`expiring` means less than 3600 seconds remain. Both automated Promotion edges
revalidate the Bundle and reject it unless at least 3600 seconds remain.
Expired, scope-drifted, or release-drifted evidence triggers a new
qualification. Invalid evidence blocks execution for investigation. A release
already merged downstream does not move backwards when older upstream evidence
expires.

Configure branch protection so both `validate / quality-gates` and
`validate / demo-api release currentness` are required and branches must be
current before merge. Long-lived Promotion PRs must rerun current checks and
may need a fresh Qualification Bundle.

## Governed rollback handoff

For selected dev/test runtime failures, the Attempt writer may resolve the most
recent previous target-release-only commit for the same environment. The
resolver is read-only and emits an exact manual command. It never calls the
rollback workflow.

Example handoff command:

```bash
gh workflow run demo-api-rollback.yaml \
  --ref main \
  -f target_environment=aws-test \
  -f rollback_to_revision=<full-historical-sha> \
  -f expected_current_release_id=<failed-release-id>
```

The rollback job enters the target GitHub Environment, rechecks that the failed
Release is still current, verifies the historical immutable image, and creates
one release-only PR. It never merges the PR, writes Kubernetes, syncs Argo CD,
aborts a Rollout, changes a Secret/database, or performs automatic rollback.

Production rollback remains a separately reviewed manual operation; the
orchestrator does not generate a production rollback handoff.

## Offline validation

```bash
./scripts/validate-demo-api-release-orchestrator.sh
./scripts/validate-demo-api-qualification-bundle.sh
./scripts/validate-trusted-runtime-executor.sh
./scripts/validate-ci-quality-gates.sh
git diff --check
```

The final interrupted-run, supersede, expiry, rollback, cost cleanup, and
clean-room environment exercises remain in v0.10.8.
