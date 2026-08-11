# Reusable Delivery Stages

v0.10.1 turns the existing v0.9 delivery workflows into stable, reusable stage
interfaces. The workflows retain their current manual or push entrypoints and
also expose `workflow_call` inputs and outputs for the event-driven orchestrator
planned in v0.10.2.

This increment does not add the orchestrator and does not grant GitHub-hosted
runners access to AWS or EKS.

## Stage Catalog

| Stage | Workflow | Durable result |
| --- | --- | --- |
| Image publish | `demo-api-image-publish.yaml` | Immutable digest, metadata, attestations, and optional aws-dev release PR |
| Static qualification | `demo-api-record-release-evidence.yaml` | Reviewable static-evidence-only PR |
| Environment promotion | `demo-api-promote-environment.yaml` | Reviewable target-release-only PR |
| Rollback handoff | `demo-api-rollback.yaml` | Reviewable historical target-release-only PR |

The machine-readable interface is
`delivery/contracts/demo-api-stages.json`. It is the source for stage names,
workflow paths, inputs, outputs, script primitives, allowed environments or
promotion edges, and mutation scopes.

## Compatibility Model

The existing operator entrypoints remain valid:

- source changes on `main` still invoke image publishing;
- every stage retains `workflow_dispatch` for reviewed manual operation;
- the input names used by v0.9 remain unchanged;
- existing scripts remain the implementation primitives;
- evidence and release files retain their v0.9 schemas and paths.

The reusable image stage additionally requires the caller to pass
`caller_ref: ${{ github.ref }}`. It verifies that value and the actual
`GITHUB_REF` are both `refs/heads/main`. Manual feature-branch validation does
not define this workflow-call-only input and therefore keeps its existing
behavior.

`workflow_call` is additive. A future caller can invoke the same reviewed
implementation without copying its shell logic into a new workflow.

## Stage Interface Rules

Every reusable stage must:

- declare typed `workflow_call` inputs;
- expose machine-readable outputs needed to derive the next release fact;
- invoke repository-owned script primitives for release mutation or evidence;
- use a GitHub-hosted runner with no AWS credentials or cluster access;
- reject pull-request code as a stage entrypoint;
- preserve the existing stale-main, immutable-image, release-only diff, and
  evidence validation checks;
- create or prepare a pull request without merging it.

The `image-publish` stage is the only stage allowed to write the GHCR image and
attestations. Its optional aws-dev PR remains release-only. The other stages
operate from protected `main` and bind their result to the captured main
revision.

## Inputs and Outputs

Stage inputs identify the requested operation; outputs describe the durable
result. Outputs do not become a new source of truth. The v0.10.2 orchestrator
must confirm them again through Git, GitHub, image, evidence, and runtime facts
when it derives state.

Important output groups are:

- image identity: repository, tag, digest, and metadata artifact name;
- qualification: evidence file, image reference, and qualified main revision;
- promotion: target release path and promoted image/source identity;
- rollback: historical revision and restored image identity;
- pull-request result: stage status and PR URL.

An empty optional output means that the optional job did not run. It must not
be interpreted as a completed gate.

## Execution and Production Boundaries

All four stages run on GitHub-hosted runners and keep:

```text
AWS credentials: none
EKS access: none
automatic merge: false
automatic environment creation: false
```

The ordered Promotion and rollback stages continue to bind the GitHub
Environment named by the target. `deployment: false` records that the workflow
prepares reviewed Git desired state rather than directly deploying a runtime.

An aws-prod Promotion or rollback can therefore prepare a PR only after the
configured Environment control is satisfied. It cannot merge the PR, apply
Terraform, create EKS, mutate a Secret or database, or run a production
rollback automatically.

## Runtime Qualification Boundary

AWS runtime qualification is deliberately absent from the reusable
GitHub-hosted stage catalog. The existing restricted operator script remains
the v0.9 compatibility path. v0.10.3 will introduce a separate trusted-runtime
stage using protected `main`, environment-isolated permissions, and short-lived
OIDC credentials.

This separation prevents the v0.10.2 GitHub-hosted orchestrator from gaining
cluster access simply because it can call reusable delivery stages.

## Retry and Idempotency Scope

v0.10.1 makes each stage independently callable and exposes enough output to
resume at a later event. It does not yet claim end-to-end idempotent
orchestration. Deterministic orchestration keys, duplicate-PR reconciliation,
supersede handling, and interrupted-run recovery are implemented and tested in
the later orchestration and failure-hardening increments.

Until then, manual stage retries retain the existing stale-main and diff-scope
guards. A retry never authorizes an automatic production change.

## Validation

Run the offline stage validator:

```bash
./scripts/validate-reusable-delivery-stages.sh
```

It checks the contract, workflow-call interfaces, declared outputs, script
references, runner and cloud-access boundaries, manual compatibility triggers,
Environment bindings, and production no-auto-merge contract. It also performs
negative contract mutations to prove that unsafe stage definitions are
rejected.

The repository-wide quality gate invokes the same validator:

```bash
./scripts/validate-ci-quality-gates.sh
```

The standalone stage validator needs only Bash and Python 3. The complete
quality gate retains the repository's Docker and Helm prerequisites.
