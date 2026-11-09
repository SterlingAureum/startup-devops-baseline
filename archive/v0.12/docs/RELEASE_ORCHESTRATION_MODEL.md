# Release Orchestration Model

This document defines the v0.10 release-orchestration contract. v0.10.0 is a
design and validation checkpoint: it defines the facts, states, transitions,
execution boundaries, and production controls that later increments automate.
It does not add a release orchestrator or grant CI access to AWS or EKS.

## Objectives

The orchestration layer must turn the existing v0.9 build, GitOps Promotion,
runtime evidence, and rollback primitives into a resumable process without
making a workflow run the permanent source of truth.

The model has five core properties:

- one application source commit and immutable image digest identify a release;
- the release identity remains unchanged across aws-dev, aws-test, and aws-prod;
- current state is derived again from durable Git, GitHub, image, evidence, and
  runtime facts whenever orchestration starts or resumes;
- an absent disposable environment pauses delivery without rebuilding the
  image or creating EKS automatically;
- production approval and the production release PR remain human controls.

The machine-readable application contract is
`delivery/contracts/demo-api.json`. Derived state snapshots follow
`delivery/contracts/release-state.schema.json`.

## Release Identity

The canonical release ID is:

```text
demo-api-<source-commit-first-12>-<image-digest-first-12>
```

For example:

```text
demo-api-04ca5ab03d99-fcfa4f473dd0
```

The complete identity retains:

- source repository;
- full 40-character source commit;
- image repository;
- full `sha256:` image digest;
- human-readable immutable image tag;
- build workflow run ID.

The workflow run ID is traceability metadata only. It is deliberately excluded
from the release ID so a safe workflow retry does not create a second business
release. Environment names are also excluded because the same artifact moves
through all environments.

## Durable Facts, Not Mutable Workflow State

An orchestrator must recompute state from these approved fact classes:

| Fact | Durable source |
| --- | --- |
| Source acceptance | protected `main` commit |
| Image identity | GHCR digest, build metadata, and attestation |
| Desired release | environment release values in `main` |
| Review state | open or merged PRs, checks, and approvals |
| Qualification | reviewed, release-bound, fresh evidence |
| GitOps runtime | Argo CD revision, sync, and health |
| Progressive delivery | Rollout and AnalysisRun status |
| Workload identity | Pod image ID and application version |
| Service result | HTTPS health, readiness, and version responses |

Job outputs, temporary environment variables, runner workspaces, and a mutable
`current-state.json` are not durable facts. A final append-only closure record
may be written after production release completion, but it records the result;
it does not drive intermediate orchestration.

## Phase and Status

Phase answers which release gate is being evaluated. Status answers why the
orchestrator is progressing, waiting, or stopped.

| Phase | Required gate before advancing |
| --- | --- |
| `source` | accepted protected-main source identity |
| `image` | immutable digest, metadata, and attestation |
| `dev-release` | reviewed or policy-approved aws-dev release PR |
| `dev-qualification` | converged dev GitOps and fresh qualification |
| `test-release` | reviewed or policy-approved aws-test Promotion PR |
| `test-qualification` | successful test Rollout, AnalysisRun, and runtime checks |
| `prod-approval` | explicit production Environment approval |
| `prod-release` | reviewed aws-prod release-only PR |
| `complete` | production release merged and closure fact recorded |

The allowed statuses are:

```text
progressing
waiting_review
waiting_runtime
waiting_environment
blocked
failed
superseded
completed
```

For example, when aws-test was intentionally destroyed to avoid portfolio
cost, the derived state is:

```json
{
  "phase": "test-release",
  "status": "waiting_environment",
  "reason": "environment-absent"
}
```

After the operator restores and bootstraps aws-test, a resume event derives the
state again and continues with the same release ID and image digest.

## Ordered Transitions

The only successful phase path is:

```text
source
  -> image
  -> dev-release
  -> dev-qualification
  -> test-release
  -> test-qualification
  -> prod-approval
  -> prod-release
  -> complete
```

No transition may skip an environment or a qualification gate. Waiting,
blocked, and failed statuses are resumable after their reason is corrected.
`superseded` and `completed` are terminal. Superseding a release never changes
the immutable identity of either the old or replacement release.

## Idempotency and Resume

Every orchestration action must use deterministic keys derived from the
release ID, phase, and target environment. Repeated events must locate and
reuse an existing branch, PR, evidence record, or completed gate rather than
create a duplicate.

Later implementations must support:

- start from a newly built release;
- status-only state derivation with no mutation;
- resume after PR merge, runner interruption, or environment restoration;
- safe retry of an idempotent stage;
- supersede when a newer accepted source release replaces an incomplete one.

The design intentionally avoids a single workflow run that waits across every
PR review and environment lifecycle event.

## Execution Policies

The contract defines two policies while v0.10.0 implements neither automatic
merge path:

| Policy | aws-dev and aws-test | aws-prod |
| --- | --- | --- |
| `reviewed` | PR review and manual merge | approval, review, and manual merge |
| `continuous-nonprod` | automatic only after required checks | approval, review, and manual merge |

The public repository defaults to `reviewed`. A private commercial deployment
may later enable `continuous-nonprod` without changing the production policy.
Configuration cannot override the production boundary.

## Execution Boundaries

### GitHub-hosted execution

GitHub-hosted jobs may build, scan, attest, statically validate, derive state,
and prepare pull requests. They do not receive AWS credentials and cannot
access EKS.

### Trusted runtime execution

Runtime qualification requires an environment-isolated trusted executor. It
must:

- run only protected `refs/heads/main` code;
- reject pull-request and fork code;
- obtain short-lived AWS credentials through OIDC;
- use environment-specific IAM and Kubernetes RBAC;
- collect only the Argo CD, Rollout, AnalysisRun, Pod identity, and HTTPS facts
  required by the release stage.

Runner registration, OIDC roles, IAM policies, and RBAC are v0.10.3 scope, not
part of this checkpoint.

### Human execution

Humans retain production Environment approval, production PR review and merge,
exception disposition, and rollback PR merge.

## Production Boundaries

Application release automation must never:

- automatically merge an aws-prod PR;
- bypass the aws-prod Environment approval;
- automatically create an EKS cluster;
- run Terraform apply as a side effect of application delivery;
- mutate production databases or Secrets;
- automatically execute a production rollback.

A failed AnalysisRun or runtime qualification stops progression, records a
diagnostic reason, and may later prepare a reviewable rollback handoff. It does
not make an unreviewed production change.

## v0.10.0 Validation

Run the offline contract validator:

```bash
./scripts/validate-release-orchestration-contract.sh
```

The validator checks the canonical environment chain, unique release paths,
cross-environment release identity, state schema alignment, transition
reachability, runner boundaries, production controls, and the example state.
It also mutates the contract in memory and proves that unsafe alternatives are
rejected, including environment skipping, production auto-merge, automatic EKS
creation, PR code on the runtime executor, cluster access from GitHub-hosted
jobs, duplicate release paths, unsafe release IDs, and undeclared transitions.

The repository-wide quality gate invokes the same validator:

```bash
./scripts/validate-ci-quality-gates.sh
```

The complete gate still requires the existing Docker and Helm prerequisites.
The orchestration contract validator itself requires only Bash and Python 3
and does not require AWS, GitHub, Kubernetes, Docker, or Helm access.

## Deferred Implementation

This checkpoint does not add:

- the event-driven orchestration workflow;
- automatic release, evidence, or Promotion PR creation;
- a trusted runner registration or cloud permission;
- automatic Argo CD or Rollout waiting;
- qualification evidence consolidation;
- live AWS acceptance.

Those capabilities are added incrementally only after this contract remains
stable under repository review.
