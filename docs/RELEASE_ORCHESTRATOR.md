# Event-Driven Release Orchestrator

v0.10.2 added the read-only control plane for the demo-api release path. It
recomputes the current phase, status, blocker, open pull request, and recommended
next action from durable Git and GitHub facts. It does not keep a mutable
`current-state.json` file and does not wait inside one long-running workflow.

v0.10.7 preserves the read-only derivation job and authorizes four bounded,
repository-variable-gated actions: `qualify-aws-dev`,
`prepare-test-promotion`, `qualify-aws-test`, and `prepare-prod-promotion`.
They may create only a target release-only PR or a qualification-only dev/test
Bundle PR. They never merge a PR, write Kubernetes, or run production runtime
qualification.

## Scope

The orchestrator runs for relevant changes on protected `main` and supports
four manual operations:

| Operation | Purpose |
| --- | --- |
| `start` | Treat the current protected-main revision as a new source candidate. |
| `status` | Recompute and report state; always `dispatchAuthorized=false`. |
| `resume` | Recompute a waiting or blocked release after its external fact changed. |
| `retry` | Start a new Attempt from one exact safely retryable failed Attempt. |

Execution additionally requires the exact variable for the recommended action:

| Action | Repository variable |
| --- | --- |
| `qualify-aws-dev` | `DEMO_API_AWS_DEV_QUALIFICATION_ENABLED=true` |
| `prepare-test-promotion` | `DEMO_API_AWS_TEST_PROMOTION_ENABLED=true` |
| `qualify-aws-test` | `DEMO_API_AWS_TEST_QUALIFICATION_ENABLED=true` |
| `prepare-prod-promotion` | `DEMO_API_AWS_PROD_PROMOTION_ENABLED=true` |

The production action additionally enters the protected `aws-prod` GitHub
Environment and cannot begin until a configured reviewer approves it.

## Event Model

The workflow starts automatically when protected `main` changes in one of these
areas:

- demo-api source, tests, image build inputs;
- aws-dev, aws-test, or aws-prod release values;
- reviewed static or runtime evidence;
- the orchestrator contract, scripts, or workflow.

A source change is interpreted as `start`. A release, evidence, or orchestrator
change is interpreted as `resume`. Pull-request code, `workflow_run` chains,
scheduled polling, and tag events are not orchestrator entrypoints.

Manual commands are:

```bash
gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=status \
  -f policy=reviewed

gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=retry \
  -f release_id=<release-id> \
  -f retry_run_id=<prior-run-id> \
  -f retry_run_attempt=<prior-run-attempt> \
  -f test_rollout_gate=not-reviewed \
  -f policy=reviewed

gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=resume \
  -f release_id=demo-api-04ca5ab03d99-fcfa4f473dd0 \
  -f test_rollout_gate=not-reviewed \
  -f policy=reviewed
```

`release_id` is optional. When omitted, the collector prefers the release bound
to the newest relevant open PR, then the current aws-dev release. A supplied ID
must resolve to a release on `main` or an open release/evidence PR.

## Fact Collection

The collector reads:

- the three environment release files on checked-out protected `main`;
- matching reviewed static and runtime evidence already in Git;
- relevant open PRs targeting `main`;
- the exact release or evidence file on each candidate PR head;
- the protected-main revision before and after derivation.

PR titles and branch names are not trusted as release identity. The collector
reads the changed release/evidence file and reconstructs the deterministic
Release ID from its full source commit and image digest. A PR is considered
relevant only when its diff contains exactly one recognized release or evidence
file. Multiple open PRs for the same release, target, and mutation kind are an
ambiguous state and stop planning.

The derived snapshot and decision are uploaded as short-retention workflow
artifacts for troubleshooting. They are observations, not a new persistent
state authority.

## Decision Model

The planner follows the v0.10 phase order and returns one recommendation:

| Observed condition | Derived state | Recommendation |
| --- | --- | --- |
| Image identity not assigned | `source / progressing` | publish image and prepare dev |
| Open target release PR | target release phase / `waiting_review` | wait for the existing PR |
| aws-dev release is on `main`, Bundle missing/stale | `dev-qualification / progressing` | qualify aws-dev |
| Matching aws-dev Bundle PR open | `dev-qualification / waiting_review` | wait for review |
| Fresh aws-dev Bundle merged | `test-release / progressing` | prepare reviewed test Promotion PR |
| aws-test release merged, Canary not confirmed | `test-qualification / waiting_review` | review and complete test Canary |
| Canary confirmed, test Bundle missing/stale | `test-qualification / progressing` | qualify aws-test |
| Matching aws-test Bundle PR open | `test-qualification / waiting_review` | wait for review |
| Required disposable environment is absent | qualification phase / `waiting_environment` | restore the environment, then resume |
| aws-test is qualified | `prod-approval / waiting_review` | enter prod Environment and prepare reviewed prod Promotion |
| aws-prod carries the same Release ID | `complete / completed` | none |
| `main` changed during derivation | current phase / `blocked` | retry after `main` stabilizes |

Once a downstream environment carries the release, expired evidence from an
already completed earlier transition does not move the release backwards. For
example, an aws-prod release remains complete after its old dev evidence expires.
Freshness is evaluated only for the next transition that has not yet occurred.

## Idempotency, Retry, and Recovery

Every run begins from current durable facts. Re-running `status` or `resume`
does not create a second Qualification Bundle PR when one already exists. The
collector recognizes the exact Bundle path and immutable release identity; the
planner points to that PR and returns `wait-for-review`.

Concurrency is serialized by application and requested release key, with
`cancel-in-progress: false`. A newer event therefore cannot cancel another
release derivation halfway through. The workflow captures checked-out `main`,
rechecks the remote protected ref after derivation, and converts a changed ref
into the resumable `stale-main` blocker.

Every derived run records a secret-free Attempt artifact for 14 days. It is
diagnostic data, not Promotion evidence. `retry` accepts only the same repository
and Release, a `blocked` or `failed` outcome, and `safe-new-attempt` retry class.
A partial GitHub job re-run is not a valid same-run, same-attempt qualification
retry. Bundle expiry/drift, supersede, and rollback handoff details are in
[Release Failure Recovery](RELEASE_FAILURE_RECOVERY.md).

## Security Boundary

The v0.10.7 derivation job still has only:

```text
contents: read
pull-requests: read
actions: read (only to download an explicitly named retry Attempt)
```

The complete workflow may additionally prepare one aws-test or aws-prod
release-only PR or one dev/test Qualification Bundle PR, but it still cannot:

- create a production PR without the fresh test Bundle and aws-prod Environment approval;
- create a rollback PR;
- merge or auto-merge any PR;
- publish or rebuild an image;
- obtain AWS credentials in a GitHub-hosted job;
- use the trusted executor for aws-prod;
- create an environment or apply Terraform;
- promote, abort, apply, or sync any Kubernetes resource;
- bypass the aws-prod Environment or reviewed PR controls;
- execute a rollback.

v0.10.3 adds the separate trusted runtime executor. v0.10.4 activates aws-dev
qualification. v0.10.5 activates reviewed test PR preparation and post-Canary
aws-test qualification. v0.10.6 activates only the Environment-approved,
release-only prod PR preparation while retaining manual merge and all runtime
production exclusions.

## Validation

Run the offline validator:

```bash
./scripts/validate-demo-api-release-orchestrator.sh
```

It validates the contracts, schemas, triggers, permissions, protected-main
recheck, PR discovery boundary, bounded reviewed dispatch, manual Canary gate,
production Environment/PR gates, and positive state cases.
It also proves that PR-code entry, `workflow_run` chaining, mutable state,
duplicate Bundle preparation, cross-run artifacts, mixed legacy/Bundle inputs,
Canary-gate bypass, production runtime or approval bypass, and automatic merge mutations
are rejected.

The repository-wide quality gate invokes the same validator:

```bash
./scripts/validate-ci-quality-gates.sh
```
