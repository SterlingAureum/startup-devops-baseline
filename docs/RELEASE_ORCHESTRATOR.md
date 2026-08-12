# Event-Driven Release Orchestrator

v0.10.2 added the read-only control plane for the demo-api release path. It
recomputes the current phase, status, blocker, open pull request, and recommended
next action from durable Git and GitHub facts. It does not keep a mutable
`current-state.json` file and does not wait inside one long-running workflow.

v0.10.5 preserves the read-only derivation job and authorizes three bounded,
repository-variable-gated actions: `qualify-aws-dev`,
`prepare-test-promotion`, and `qualify-aws-test`. They may create only a
release-only aws-test PR or a qualification-only dev/test Bundle PR. They never
merge a PR, write Kubernetes, or prepare production.

## Scope

The orchestrator runs for relevant changes on protected `main` and supports
three manual operations:

| Operation | Purpose |
| --- | --- |
| `start` | Treat the current protected-main revision as a new source candidate. |
| `status` | Recompute and report state without changing the release. |
| `resume` | Recompute a waiting or blocked release after its external fact changed. |

Execution additionally requires the exact variable for the recommended action:

| Action | Repository variable |
| --- | --- |
| `qualify-aws-dev` | `DEMO_API_AWS_DEV_QUALIFICATION_ENABLED=true` |
| `prepare-test-promotion` | `DEMO_API_AWS_TEST_PROMOTION_ENABLED=true` |
| `qualify-aws-test` | `DEMO_API_AWS_TEST_QUALIFICATION_ENABLED=true` |

`prepare-prod-promotion` is always plan-only in v0.10.5.

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
| aws-test is qualified | `prod-approval / waiting_review` | prepare reviewed prod Promotion |
| aws-prod carries the same Release ID | `complete / completed` | none |
| `main` changed during derivation | current phase / `blocked` | retry after `main` stabilizes |

Once a downstream environment carries the release, expired evidence from an
already completed earlier transition does not move the release backwards. For
example, an aws-prod release remains complete after its old dev evidence expires.
Freshness is evaluated only for the next transition that has not yet occurred.

## Idempotency and Resume

Every run begins from current durable facts. Re-running `status` or `resume`
does not create a second Qualification Bundle PR when one already exists. The
collector recognizes the exact Bundle path and immutable release identity; the
planner points to that PR and returns `wait-for-review`.

Concurrency is serialized by application and requested release key, with
`cancel-in-progress: false`. A newer event therefore cannot cancel another
release derivation halfway through. The workflow captures checked-out `main`,
rechecks the remote protected ref after derivation, and converts a changed ref
into the resumable `stale-main` blocker.

## Security Boundary

The v0.10.5 derivation job still has only:

```text
contents: read
pull-requests: read
```

The complete workflow may additionally prepare one aws-test release-only PR or
one dev/test Qualification Bundle PR, but it still cannot:

- create a production or rollback PR;
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
aws-test qualification. v0.10.6 retains the production boundary.

## Validation

Run the offline validator:

```bash
./scripts/validate-demo-api-release-orchestrator.sh
```

It validates the contracts, schemas, triggers, permissions, protected-main
recheck, PR discovery boundary, bounded dev/test dispatch, manual Canary gate,
and positive state cases.
It also proves that PR-code entry, `workflow_run` chaining, mutable state,
duplicate Bundle preparation, cross-run artifacts, mixed legacy/Bundle inputs,
Canary-gate bypass, production runtime/dispatch, and automatic merge mutations
are rejected.

The repository-wide quality gate invokes the same validator:

```bash
./scripts/validate-ci-quality-gates.sh
```
