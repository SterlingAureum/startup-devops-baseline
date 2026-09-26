# startup-devops-baseline

A local-first DevOps, GitOps, progressive delivery, and AWS EKS infrastructure baseline for early-stage teams.

Current development checkpoint:
`v0.12.2.2.1-bootstrap-state-migration-recovery-evidence` records the terminal
redacted evidence for the successful read-only identity-rebase recovery. The
remote state has one current object version and no delete marker; no migration
or Terraform mutation was repeated. See
[v0.12.2.2.1 migration recovery evidence](docs/V0.12.2.2.1_BOOTSTRAP_STATE_MIGRATION_RECOVERY_EVIDENCE.md).

Predecessor development checkpoint:
`v0.12.2.2.0.2-identity-rebase-digest-encoding-repair` restores the single LF
byte used by the reviewed identity-rebase evidence digest format. It changes no
digest, state, evidence or live authority and requires a new recovery request
after merge. See
[v0.12.2.2.0.2 identity-rebase digest repair](docs/V0.12.2.2.0.2_IDENTITY_REBASE_DIGEST_ENCODING_REPAIR.md).

Predecessor development checkpoint:
`v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery` binds the exact
post-migration identity-rebase incident and adds command-free verification plus
a separately approved read-only continuation. It never repeats init or state
migration. Applying the increment performs no live operation. See
[v0.12.2.2.0.1 bootstrap state identity-rebase recovery](docs/V0.12.2.2.0.1_BOOTSTRAP_STATE_IDENTITY_REBASE_RECOVERY.md).

Predecessor development checkpoint:
`v0.12.2.2-reviewed-bootstrap-state-migration` added the one-shot reviewed
local-to-S3 migration executor. Its approved init migration configured the
backend and copied exact state content before the strict lineage gate stopped.
See [v0.12.2.2 reviewed bootstrap state migration](docs/V0.12.2.2_REVIEWED_BOOTSTRAP_STATE_MIGRATION.md).

Predecessor development checkpoint:
`v0.12.2.1-private-bootstrap-migration-preflight` declares the empty partial
S3 backend and adds command-free verification plus a separately approved,
read-only preflight that preserves a third private state copy and produces an
exact private migration command plan. It does not initialize the backend or
migrate state. See
[v0.12.2.1 private bootstrap migration preflight](docs/V0.12.2.1_PRIVATE_BOOTSTRAP_MIGRATION_PREFLIGHT.md).

Predecessor development checkpoint:
`v0.12.2.0.1-private-bootstrap-state-location-repair` corrects the migration
source from an unused repository-root path to the byte-identical private plan-
bundle working state and preserved apply copy verified by recovery. It performs
no live operation. See
[v0.12.2.0.1 private bootstrap-state location repair](docs/V0.12.2.0.1_PRIVATE_BOOTSTRAP_STATE_LOCATION_REPAIR.md).

Predecessor development checkpoint:
`v0.12.2.0-state-migration-design-foundation` defines the offline safety
contract and phased authority boundary for the first non-empty bootstrap-state
migration. It changes no backend, runs no Terraform or AWS command and grants
no migration authority. See
[v0.12.2.0 state-migration design foundation](docs/V0.12.2.0_STATE_MIGRATION_DESIGN_FOUNDATION.md).

Predecessor development checkpoint:
`v0.12.1.2.1-state-bootstrap-execution-evidence` records the redacted terminal
evidence for the reviewed state-bootstrap creation and read-only recovery. The
foundation is live-validated, the bootstrap state remains private and local,
and no state migration has occurred. See
[v0.12.1.2.1 state-bootstrap execution evidence](docs/V0.12.1.2.1_STATE_BOOTSTRAP_EXECUTION_EVIDENCE.md).

Predecessor development checkpoint:
`v0.12.1.2.0.1-state-bootstrap-post-apply-recovery` repairs the KMS
rotation-status identifier and adds a separately approved read-only recovery
for an apply that completed before post-apply validation stopped. It cannot
repeat apply, destroy, attach policies or migrate state. See
[v0.12.1.2.0.1 state-bootstrap post-apply recovery](docs/V0.12.1.2.0.1_STATE_BOOTSTRAP_POST_APPLY_RECOVERY.md).

Predecessor development checkpoint:
`v0.12.1.2-reviewed-state-bootstrap-apply` adds a separately approved consumer
for one fresh, human-reviewed v0.12.1.1 saved plan. It revalidates every private
artifact and the live S3/KMS/IAM foundation while retaining local bootstrap
state; applying this repository increment performs no live operation. See
[v0.12.1.2 reviewed state-bootstrap apply](docs/V0.12.1.2_REVIEWED_STATE_BOOTSTRAP_APPLY.md).

Predecessor development checkpoint:
`v0.12.1.1-guarded-state-bootstrap-plan` adds a protected-main, private-input,
bounded-approval entry point that can verify or produce one exact create-only
saved plan for the v0.12.1 state foundation. It cannot apply the plan, create
backend resources or migrate state. See
[v0.12.1.1 guarded state-bootstrap plan](docs/V0.12.1.1_GUARDED_STATE_BOOTSTRAP_PLAN.md).

Predecessor development checkpoint:
`v0.12.1.0.1-ci-compatibility-repair` restores the four still-local Terraform
roots to their reviewed v0.11 version-constraint bytes and canonicalizes the
new state-bootstrap HCL formatting. The bootstrap and future remote-backend
path retain the Terraform 1.11 floor; no backend resource or state is changed.
See [v0.12.1.0.1 CI compatibility repair](docs/V0.12.1.0.1_CI_COMPATIBILITY_REPAIR.md).

Predecessor development checkpoint:
`v0.12.1-remote-state-foundation` implements the independent state-bootstrap
root, encrypted/versioned S3 declaration, S3-native lock keys, root-scoped IAM
policies and partial backend examples. See
[v0.12.1 remote-state foundation](docs/V0.12.1_REMOTE_STATE_FOUNDATION.md).

Predecessor development checkpoint:
`v0.12.0-production-readiness-foundation` starts the Production Readiness
Capstone and freezes its state, lifecycle, upgrade, recovery, documentation
and AI-governance boundaries. See
[v0.12.0 production-readiness foundation](docs/V0.12.0_PRODUCTION_READINESS_FOUNDATION.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.20.1-roadmap-status-successor-repair` preserves the
evidence-bound v0.11 completion state and its explicit production-readiness
deferrals. See [roadmap status successor repair](docs/V0.11.9.3.6.7.7.20.1_ROADMAP_STATUS_SUCCESSOR_REPAIR.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.20-v0.11-scope-and-evidence-closure` closes the v0.11
Observability and SRE capability scope while keeping local, aws-dev, aws-test,
and aws-prod evidence distinct. Local and aws-dev have live qualification
evidence; aws-test has separate historical feature-observation and current
clean-room deployment/cleanup evidence; aws-prod live acceptance and full
production readiness remain deferred to v0.12. No live authority is added. See
[v0.11 scope and evidence closure](docs/V0.11.9.3.6.7.7.20_V0.11_SCOPE_AND_EVIDENCE_CLOSURE.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.19-dev-local-offline-process-chain` exercises all eight
aws-dev phases through sixteen fresh `.7.7.18` verify/execute processes. It
retains strict private bundle, preflight, stdout/stderr, redacted-manifest and
restart-safe receipt artifacts while keeping every live effect disabled. See
[dev local offline process chain](docs/V0.11.9.3.6.7.7.19_DEV_LOCAL_OFFLINE_PROCESS_CHAIN.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.18-dev-local-offline-command` adds strict local `verify` and
`execute` commands above the restart-safe adapter. Exact canonical bundle and
preflight hashes, separate confirmations, fresh clocks and receipt-prefix
revalidation guard one fixed-fake attempt. No live backend or authority exists.
See [dev local offline command](docs/V0.11.9.3.6.7.7.18_DEV_LOCAL_OFFLINE_COMMAND.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.17-dev-restart-safe-receipt-adapter` composes the injected
aws-dev protocol with an owned `0700` local receipt directory, exclusive
fsynced `0600` attempt/receipt/completion triplets and the same fixed fake.
Restart, fault and tamper checks fail closed; no live backend, credential
reader or command exists. See
[dev restart-safe receipt adapter](docs/V0.11.9.3.6.7.7.17_DEV_RESTART_SAFE_RECEIPT_ADAPTER.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.16-dev-injected-transport-protocol` implements the closed
aws-dev protocol as a pure injected core and fixed-fake harness. It exercises
all eight stages and 23 operations with write-ahead in-memory intents, exact
responses, postcondition gates and non-live terminal records. No live backend,
durable live receipt or command exists. See
[dev injected transport protocol](docs/V0.11.9.3.6.7.7.16_DEV_INJECTED_TRANSPORT_PROTOCOL.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.15-dev-live-transport-design` closes the dev-only versioned
transport interface across eight stages and 23 exact operations. Each stage
requires exact approval, proof, state and predecessor-receipt bindings; only
the two Terraform delete stages accept reviewed saved-plan bundles. The live
backend, command and execution authority remain disabled. See
[dev live transport design](docs/V0.11.9.3.6.7.7.15_DEV_LIVE_TRANSPORT_DESIGN.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.14-dev-live-parity-gap-review` compares the complete
eight-stage fixed-fake chain with the closed aws-dev teardown and residual
audit evidence. It preserves ten proven historical controls but identifies
eight structural gaps and zero equivalent historical live stage receipts. No
live transport or authority is added. See
[dev live parity gap review](docs/V0.11.9.3.6.7.7.14_DEV_LIVE_PARITY_GAP_REVIEW.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.13-dev-local-offline-restart-chain` runs the complete aws-dev
eight-phase chain through 16 separate preflight/execute child processes, 23
closed fixed-fake operations and eight restart-safe receipt triplets. Synthetic
fixtures and receipts cannot grant or seed live authority. See
[dev local offline restart chain](docs/V0.11.9.3.6.7.7.13_DEV_LOCAL_OFFLINE_RESTART_CHAIN.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.12-dev-local-offline-execute` adds a separately invoked
aws-dev local `execute` command that requires a fresh `.7.7.11` preflight,
runs only the closed fixed fake and appends one durable offline receipt. It
cannot access a live backend. See
[dev local offline execute](docs/V0.11.9.3.6.7.7.12_DEV_LOCAL_OFFLINE_EXECUTE.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.11-dev-local-cli-preflight` adds a dev-only local `verify`
command with one host UTC read and exactly two strict private-file reads. It
validates the inherited durable receipt prefix but cannot execute a transport
or write a receipt. See
[dev local CLI preflight](docs/V0.11.9.3.6.7.7.11_DEV_LOCAL_CLI_PREFLIGHT.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.10-dev-offline-command-entry-conformance` composes separate
verify/execute commands with injected clocks and canonical private fixture bytes
through the dev-only fixed fake and durable receipt store. It adds no CLI, real
private reader or live backend. See
[dev command-entry conformance](docs/V0.11.9.3.6.7.7.10_DEV_OFFLINE_COMMAND_ENTRY_CONFORMANCE.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.9-dev-offline-transport-conformance-and-durable-receipts`
exercises the exact eight-stage/23-operation interface through a dev-only fixed
fake and implements an append-only local receipt triplet with restart and fault
coverage. No live backend or command entry point is enabled. See
[dev transport conformance](docs/V0.11.9.3.6.7.7.9_DEV_OFFLINE_TRANSPORT_CONFORMANCE_AND_DURABLE_RECEIPTS.md).

Earlier development checkpoint:
`v0.11.9.3.6.7.7.8-live-transport-and-receipt-migration-design` defines the
closed versioned transport, separate phase approval and durable receipt handoff
required before live migration. Synthetic receipts cannot become live evidence;
no environment is enabled and prod remains disabled. See
[live migration design](docs/V0.11.9.3.6.7.7.8_LIVE_TRANSPORT_AND_RECEIPT_MIGRATION_DESIGN.md).

Earlier development checkpoint:
`v0.11.9.3.6.7.7.7-shared-offline-freeze-adapter` adds the missing fixed-fake
Application freeze/orphan/delete stage and composes confirmed synthetic receipts
through all eight dev/test/prod phases (24/24 matrix cells). See
[offline freeze adapter](docs/V0.11.9.3.6.7.7.7_SHARED_OFFLINE_FREEZE_ADAPTER.md).

Predecessor parity checkpoint:
`v0.11.9.3.6.7.7.6-complete-offline-runtime-parity-review` proves that seven of
eight ordered cleanup stages were individually simulated across dev/test/prod (21/24
matrix cells) before the freeze adapter was added. See
[runtime parity review](docs/V0.11.9.3.6.7.7.6_COMPLETE_OFFLINE_RUNTIME_PARITY_REVIEW.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.5-shared-offline-cleanup-adapters` composes five fixed-fake
ESO/runtime/namespace/node-config/ENI-SG stages across dev/test/prod with 41 offline
tests. Live migration remains pending. See
[offline cleanup adapters](docs/V0.11.9.3.6.7.7.5_SHARED_OFFLINE_CLEANUP_ADAPTERS.md).

Predecessor development checkpoint:
`v0.11.9.3.6.7.7.4-shared-offline-destroy-adapters` composes four shared cores for
EKS dependency/final stages across explicit dev/test/prod profiles, using fixed fake
transport and 39 offline tests. Live migration remains pending. See
[offline destroy adapters](docs/V0.11.9.3.6.7.7.4_SHARED_OFFLINE_DESTROY_ADAPTERS.md).

Recorded plan/journal checkpoint:
`v0.11.9.3.6.7.7.3-shared-plan-scope-and-attempt-journal` adds exact reviewed destroy
scope and a durable Linux write-ahead journal with 36 offline fixtures. Pending or
failed attempts stop; live adapter integration remains pending. See
[plan scope and attempt journal](docs/V0.11.9.3.6.7.7.3_SHARED_PLAN_SCOPE_AND_ATTEMPT_JOURNAL.md).

Recorded cleanup-rule checkpoint:
`v0.11.9.3.6.7.7.2-shared-guarded-cleanup-rules` implements dependency-order and
captured ENI/SG pure decisions with 28 offline fixtures. ESO permissions outlive
dependent cleanup; repeated attempts and changed scope fail. Live adapter migration
remains pending. See [shared cleanup rules](docs/V0.11.9.3.6.7.7.2_SHARED_GUARDED_CLEANUP_RULES.md).

Recorded pure-rule checkpoint:
`v0.11.9.3.6.7.7.1-shared-guarded-runtime-pure-rules` extracts clock/proof, exact
phase confirmations, CLI absence and managed/data state rules with 29 offline
parity tests. Existing live adapters remain frozen; common adapter migration is
pending. See [shared pure rules](docs/V0.11.9.3.6.7.7.1_SHARED_GUARDED_RUNTIME_PURE_RULES.md).

Recorded review checkpoint:
`v0.11.9.3.6.7.7-cross-environment-guarded-runtime-review` records source-bound
offline dev/test review, common module profiles and the remaining cleanup coverage
gaps. Shared runtime migration remains pending; no new live operation is enabled.
See [cross-environment review](docs/V0.11.9.3.6.7.7_CROSS_ENVIRONMENT_GUARDED_RUNTIME_REVIEW.md).

Recorded audit checkpoint:
`v0.11.9.3.6.7.6.6.3-residual-cost-audit-execution-evidence` records the passed
September 14 scoped aws-test residual audit: four instant request-history records,
four natively verified instances, ninety captured managed definitions and unchanged
empty state. Teardown/residual checks are closed; historical billing and runtime
qualification are not certified. See [audit execution evidence](docs/V0.11.9.3.6.7.6.6.3_AWS_TEST_RESIDUAL_COST_AUDIT_EXECUTION_EVIDENCE.md).

Historical repair checkpoint:
`v0.11.9.3.6.7.6.6.2-instant-fleet-classification-repair` adds a reusable typed Fleet
classifier and fresh captured-instance absence checks for active instant history.
The prior audit remains stopped; fresh proofs and separate approval are required.
See [typed Fleet repair](docs/V0.11.9.3.6.7.6.6.2_AWS_TEST_INSTANT_FLEET_CLASSIFICATION_REPAIR.md).

Predecessor implementation:
`v0.11.9.3.6.7.6.6.1-audit-error-envelope-repair` fixes the strict parser false
negative for a standard NoSuchBucket error with the zero-retry annotation.
The failed preflight remains preserved; merge requires a fresh private preflight.
See [error envelope repair](docs/V0.11.9.3.6.7.6.6.1_AWS_TEST_AUDIT_ERROR_ENVELOPE_REPAIR.md).

Predecessor implementation:
`v0.11.9.3.6.7.6.6-guarded-residual-cost-audit` implements strict aws-test
read-only preflight, verify and separately approved one-time residual inventory.
It binds completed teardown and empty state; no audit ran during implementation.
See [guarded residual-cost audit](docs/V0.11.9.3.6.7.6.6_GUARDED_AWS_TEST_RESIDUAL_COST_AUDIT.md).

Recorded predecessor:
`v0.11.9.3.6.7.6.5-teardown-execution-evidence` records completed aws-test
teardown, the separately approved ENI/SG post-apply continuation, and the
September 14 empty-state/private-evidence confirmation. At that checkpoint the full
residual audit was pending; the current evidence above records its later scoped pass.
Consumed teardown windows grant no new live authorization.
See [teardown execution evidence](docs/V0.11.9.3.6.7.6.5_AWS_TEST_TEARDOWN_EXECUTION_EVIDENCE.md).

Historical implementation checkpoint:
`v0.11.9.3.6.7.6.4-eks-dependency-plan-repair` replaces the module-only EKS gate
with the exact 50 state-bound deletes, preserves the original saved-plan clock and
requires separate fresh-plan/apply approvals. Its historical cleanup deadline was September 13 16:00 UTC.
See [exact EKS dependency repair](docs/V0.11.9.3.6.7.6.4_AWS_TEST_EKS_DEPENDENCY_PLAN_REPAIR.md).

`v0.11.9.3.6.7.6.3-remaining-cleanup` preserves two consumed runtime attempts
and the separately approved ESO finalizer repair. A read-only observation found
only two NodePools, three NodeClasses, four system nodes/root disks and retained
Terraform infrastructure. Fresh continuation deletes only those five configuration
objects before independent EKS/final saved-plan reviews. Candidate completion is
September 13 16:00Z, configuration stop 14:30Z; existing conservative allowances
project USD 35.20 against USD 36, with billing unknown. New schedule and phase
approvals are required; packaging performs no live deletion.
See [remaining cleanup](docs/V0.11.9.3.6.7.6.3_AWS_TEST_REMAINING_CLEANUP.md).
Predecessor:
`v0.11.9.3.6.7.6.2-runtime-cleanup-resume` preserved partial runtime execution
and avoided repeating already-completed freezes. Its consumed proofs and
historical window remain unchanged.
See [partial cleanup continuation](docs/V0.11.9.3.6.7.6.2_AWS_TEST_RUNTIME_CLEANUP_RESUME.md).
Predecessor:
`v0.11.9.3.6.7.6.1-cleanup-window-renewal` preserves the expired-window stop
and binds fresh cleanup proofs to the user-confirmed September 13 window:
runtime latest start 10:40Z, stop 11:00Z, cleanup complete 12:30Z. Existing reviewed
allowances project USD 29.55 against USD 36; billing is unknown and deletion still
needs independent approvals. Historical scripts/proofs stay unchanged.
See [the renewed cleanup procedure](docs/V0.11.9.3.6.7.6.1_AWS_TEST_CLEANUP_WINDOW_RENEWAL.md).
Predecessor:
`v0.11.9.3.6.7.6-guarded-aws-test-teardown` implements independently reviewed
runtime cleanup, an EKS saved destroy plan/apply and a remaining-infrastructure
saved destroy plan/apply. Every mutation needs separate approval; no cleanup
was executed while producing this increment. Fixed cleanup completion remains
September 13 10:51:13Z; runtime phases require a start by 09:01:13Z.
See [the staged teardown procedure](docs/V0.11.9.3.6.7.6_GUARDED_AWS_TEST_TEARDOWN.md).
Predecessor:
`v0.11.9.3.6.7.5.2.1-aws-test-root-execution-evidence` records the one-time
successful immutable deployment: Root/demo Healthy, database/ESO ready,
owned DNS INSYNC and unchanged state. It adds a read-only cleanup dependency
observer; no deletion executor or teardown approval is included. Preserve the
September 13 10:51:13Z cleanup-completion deadline and consumed attempt proof.
See [execution evidence and cleanup preparation](docs/V0.11.9.3.6.7.5.2.1_AWS_TEST_ROOT_EXECUTION_EVIDENCE_AND_CLEANUP.md).
Predecessor:
`v0.11.9.3.6.7.5.2-aws-test-immutable-root-deployment` implements private
immutable Root/child preparation, fresh read-only verify and separately
approved one-time Root/credential/DNS execution. The revised USD 36 total
model covers the earlier session through cleanup at September 13 10:51:13Z;
commands stop at 09:21:13Z with no automatic cleanup or billing cap. USD 20
remains an expectation. No infrastructure apply/bootstrap is repeated.
See [the immutable deployment procedure](docs/V0.11.9.3.6.7.5.2_AWS_TEST_IMMUTABLE_ROOT_DEPLOYMENT.md).
Predecessor:
`v0.11.9.3.6.7.5.1-aws-test-root-capacity-cost` adds a complete configured
node/disk ledger and offline cost-profile preparation/review. Unknown prices
stop review; elapsed next-day cost and cleanup time stay inside the USD 8
model. Root deployment still requires an immutable, bounded executor.
See [the capacity and cost procedure](docs/V0.11.9.3.6.7.5.1_AWS_TEST_ROOT_CAPACITY_COST.md).
Predecessor:
`v0.11.9.3.6.7.5-aws-test-recovery-root-design` records the expired session and
lost temporary evidence, pins the new persistent recovery observation and adds
a read-only preflight plus an offline private Root-plan checker. Historical
spend remains unknown; the USD 8 additional budget includes elapsed next-day
idle time, a conservative post-Root estimate and a cleanup reserve. Root
auto-sync, controller-created resources, credential transfer and DNS require
complete scope review. This increment contains no deployment executor.
Predecessor:
`v0.11.9.3.6.7.4.1.1-gitleaks-evidence-field-repair` removes the single
`generic-api-key` false positive reported for a SHA-256 evidence fingerprint.
It uses a neutral digest property, strengthens the complete stable-output-map
assertion and leaves `.gitleaksignore` byte-identical. The evidence value and
meaning are unchanged, no credential material is committed, and applying or
validating the repair performs no live operation.
Predecessor:
`v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence` records the
separately approved one-time aws-test platform bootstrap on exact protected
main. Argo CD `v3.5.2`, both reviewed IRSA ServiceAccounts and the AWS Load
Balancer Controller child Application passed post-checks while Terraform state
remained unchanged and the Root Application stayed absent. Raw output and
private identities remain outside Git. Applying and validating this evidence
performs no live operation.
Predecessor:
`v0.11.9.3.6.7.4-guarded-aws-test-gitops-bootstrap` adds a two-phase,
exact-main aws-test platform bootstrap. Its read-only verify requires the
reviewed live state, ACTIVE EKS, exact API boundary, ready Kubernetes API and
an empty Argo CD/bootstrap surface. A separately approved execute may install
exact Argo CD and the AWS Load Balancer Controller child Application once,
then must stop before the Root Application. Applying and validating the
increment performs no live operation.
Predecessor:
`v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence` records the
exact saved-plan apply, the fail-closed post-apply classifier incident and the
successful separately approved no-reapply resume. All 90 planned creates are
present, no extra managed address exists, aws-test EKS is ACTIVE and the
credential-container metadata check passed. Raw state, AWS output and private
identities remain outside Git. GitOps bootstrap, traffic and qualification
remain separate checkpoints.
Predecessor:
`v0.11.9.3.6.7.3.1-aws-test-state-classification-repair` distinguishes
Terraform managed addresses from the seven exact read-only data-source entries
that caused the original wrapper to stop after a successful apply. Its local
verify and AWS-read-only resume cannot run Terraform or retry apply.
Predecessor:
`v0.11.9.3.6.7.3-guarded-aws-test-terraform-apply-executor` applies one exact,
unexpired, reviewed saved plan without replanning and preserves state and
private evidence on every uncertain outcome.
Predecessor:
`v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence` records the
separately approved and human-reviewed plan-only execution on exact protected
main. The private plan contained 90 creates and six reads and passed the
create/read/no-op machine gate. Its private binary, JSON, text and record
remain outside Git and are pinned by SHA-256.
Predecessor:
`v0.11.9.3.6.7.2-guarded-aws-test-terraform-plan-executor` adds a two-phase,
exact-main executor for a private aws-test Terraform plan. Its zero-command
`verify` phase binds a fresh post-merge preflight and owner-only creation plan;
its separately approved `execute` phase may run only read-only AWS discovery
and Terraform init/plan/show. A machine gate rejects update, delete,
replacement, unknown actions and identity drift. Applying and validating this
increment performs no live operation; a new post-merge preflight, populated
private plan and separate approval are still required before planning.
Predecessor:
`v0.11.9.3.6.7.1-guarded-aws-test-private-creation-plan-design` binds the
reviewed `.6.7` readiness result and adds an offline validator for an
owner-only aws-test creation plan. It fixes exact main, candidate, account,
management-IP, local-variable, cost/time and create/read/no-op-only plan
boundaries. Merging and validating it runs no AWS or Terraform command; a
fresh post-merge preflight, a guarded plan executor and separate plan approval
are still required before Terraform planning.
Predecessor:
`v0.11.9.3.6.7-guarded-aws-test-live-creation-preflight` adds an exact-main,
exact-account read-only gate after the completed aws-dev teardown and residual
audit. It confirms no active rehearsal environment and an empty aws-test local
state without invoking Terraform or the legacy plan-and-apply wrapper.
Predecessor:
`v0.11.9.3.6.6.1-aws-test-successor-validation-repair` replaces permanent
candidate-absence assertions with an exact two-state aws-test allowlist. The
historical and reviewed promoted release bytes pass, unknown or partial
identities fail closed, and aws-prod remains unchanged. The existing promotion
PR stays held until this repair is merged and its branch is updated.
Predecessor:
`v0.11.9.3.6.6-reviewed-live-aws-test-promotion-handoff` connects the reviewed
aws-dev live qualification contract to a release-only aws-test promotion PR.
It pins the exact evidence and source-release hashes, release ID and protected
main, permits only `aws-dev -> aws-test`, and does not merge or access either
environment. Workflow dispatch, PR review/merge, aws-dev teardown and aws-test
creation remain separate checkpoints.
Predecessor:
`v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution` records the fresh
successful preflight and separately approved bounded qualification on exact
protected main `489c8036b21e`. Exactly 54 normal requests populated the
release-scoped series; availability and latency SLOs passed, no critical alert
was firing, and the final runtime stayed healthy. Raw evidence remains private
and is pinned only by SHA-256. No fault, Root/monitoring mutation,
Rollout/AnalysisRun, promotion or teardown occurred. The next environment
requires separate review. Applying and validating this evidence performs no
AWS, Kubernetes, Prometheus or traffic operation.
Predecessor:
`v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair` keeps the repaired
loopback-only Prometheus transport and corrects its remaining timing race. The
observed tunnel accepted 13 connections and cleaned up correctly, but its
one-second readiness probes expired before the ready response arrived. The
successor uses bounded 90-second startup, 10-second readiness-probe and
60-second Prometheus request budgets, and reports the last probe error. It
still stops before traffic and requires a fresh post-merge preflight plus
separate approval. Applying and validating this package performs no AWS,
Kubernetes or traffic operation.
Predecessor:
`v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair` replaces
the failed EKS API Service Proxy telemetry path with the already reviewed
loopback-only `pods/portforward` transport. It uses a dynamic port, bounded
readiness and request timeouts, an anonymous private log and deterministic
normal/error/interrupt cleanup without broadening security groups or
NetworkPolicies. The observed preflight stopped before traffic; a fresh
post-merge preflight and separate approval remain required. Applying and
validating this package performs no AWS, Kubernetes or traffic operation.
Predecessor:
`v0.11.9.3.6.5-aws-dev-runtime-qualification` implements a separately
confirmed exact-main preflight and one bounded aws-dev qualification. It
requires the immutable Deployment, database, Grafana, public HTTPS and
Prometheus target/rule inventory to be healthy before allowing at most 54
normal `/health`, `/ready` and `/version` requests. It then requires populated
request telemetry, passing availability/latency ratios and no critical alert.
aws-dev has no Rollout promotion or AnalysisRun; fault injection, aws-test
promotion and teardown remain separate. Applying and validating this package
performs no AWS, Kubernetes or traffic operation.
Predecessor:
`v0.11.9.3.6.4.3-aws-environment-teardown-convergence` records the completed
aws-dev teardown closure and repairs the shared aws-dev/aws-test destroy path.
It captures every EBS-backed PVC, waits for Root child pruning, safely
converges only exact detached dynamic-PVC volumes, detached `aws-K8S-*` ENIs
and an unreferenced EKS-created security group, inventories unknown VPC
dependencies, and requires a new interactive Terraform confirmation before
one retry. The observed final state and next-day residual audit were clean,
but the repaired path remains live-unvalidated. Applying and validating this
checkpoint performs no AWS, Terraform or Kubernetes operation.
Predecessor:
`v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution` records the
separately approved repair on exact main `6421e140b3ac`: the independent
Grafana Secret was created without exposed values, Grafana reached `1/1`, and
monitoring became `Synced / Healthy` on chart `88.5.0`. Root was not redeployed
and runtime qualification, traffic and promotion remain unexecuted at that
checkpoint.
The private log stays outside Git and is pinned only by SHA-256. Applying and
validating this evidence performs no live operation.
Predecessor:
`v0.11.9.3.6.4.1-aws-dev-monitoring-convergence` repairs the post-Root
Grafana runtime-Secret gap. It accepts only the observed missing-Secret state
or the already-converged state, creates or preserves the independent Secret
without exposing values, and requires Grafana Ready plus monitoring
`Synced / Healthy`. Root redeploy, traffic, qualification, promotion and
teardown remain outside this checkpoint. Applying and validating it performs
no live operation. An expired eight-hour review window requires a fresh plan,
live preflight and approval rather than editing the executed plan in place.
Predecessor:
`v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy` implements a
separately confirmed verify/execute gate for the first aws-dev Root tree. It
binds local, tracking and remote main; the reviewed account/EKS/Terraform
state; exact Root/release files; Argo CD `v3.5.2`; the healthy ALB Application;
Secrets Manager and Route53 containers; and Root absence. The approved write
scope includes Root, CNPG/External Secrets bootstrap and stable DNS, but never
progressive promotion, SLO qualification or teardown. Applying and validating
this checkpoint performs no live operation and hands off to `.3.6.4.1` before
runtime qualification.
Predecessor:
`v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution` records the separately
approved bootstrap on exact protected main `64fe6bb58bb5`. Argo CD `v3.5.2`
and the AWS Load Balancer Controller Application converged, all seven observed
Argo CD workloads were Ready, both IRSA accounts matched, and the Root
Application remained absent. Raw account, role, VPC and endpoint values remain
private. Applying or validating this evidence performs no live operation.
Predecessor:
`v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap` implements a separately
confirmed verify/execute gate for the existing aws-dev EKS environment. It
requires clean exact protected main, the reviewed AWS account, ACTIVE EKS,
the recorded 103-address Terraform state, `/readyz=ok`, absent Argo CD and
valid Terraform bootstrap outputs. Execution pins Argo CD `v3.5.2` and stops
before the Root Application, runtime qualification, traffic or teardown.
Applying or validating this checkpoint performs no live operation.
Predecessor:
`v0.11.9.3.6.2.1-live-state-test-isolation-repair` makes the historical mocked
ready-preflight unit test replace its filesystem state reader as well as AWS
and Git commands. The test therefore remains deterministic after aws-dev has a
real nonempty Terraform state, while production preflight and the live state
remain unchanged.
Predecessor:
`v0.11.9.3.6.2-aws-dev-infrastructure-create-execution` records the separately
approved aws-dev creation on exact protected main `b01e76c41555`. The guarded
executor repeated a byte-identical ready preflight, accepted a nonempty
create/read/no-op-only Terraform plan, created 103 state addresses and stopped
with an ACTIVE EKS 1.36 API and four Ready nodes. Argo CD, the Root Application,
runtime qualification, promotion and teardown remain separate and unexecuted.
Predecessor:
`v0.11.9.3.6.1.1-shellcheck-source-follow-repair` makes the `.3.6.1`
validation entrypoint run ShellCheck with external-source following from the
repository root. This removes deterministic `SC1091` CI/local parity failure,
adds a ShellCheck-independent invocation regression and changes no AWS,
Terraform, Kubernetes or executor runtime behavior.
Predecessor:
`v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor` implements a two-phase
verify/execute gate for initial aws-dev infrastructure. It binds three private
files to exact main, re-runs a byte-identical read-only preflight, requires
three environment confirmations plus the Terraform prompt, and accepts only a
nonempty create/read/no-op plan. Success stops at EKS API readiness; GitOps,
qualification and teardown remain separate.
Predecessor:
`v0.11.9.3.6-aws-dev-live-rehearsal-create-plan` adds an offline-only private
aws-dev creation-plan contract. It requires a fresh post-merge preflight,
exact candidate and main identities, two Terraform confirmations, a reviewed
current-price estimate, an eight-hour/one-environment ceiling, ordered GitOps
bootstrap, failure-stop rules and separately approved teardown. Validation
never executes the plan and always leaves creation unauthorized.
Predecessor:
`v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution` records the
successful read-only preflight on protected main `cd5aac1f2ab4`: no rehearsal
cluster was active, local dev state was empty, and the private plan/result are
represented only by SHA-256 fingerprints and restrictive modes. It records
the two permitted AWS reads, no mutation, and keeps creation unauthorized
until a separate reviewed plan.
Predecessor:
`v0.11.9.3.5-aws-dev-live-rehearsal-preflight` adds a private-plan and
read-only discovery gate before any billable aws-dev creation. It binds the
post-merge main SHA, candidate identity, AWS account and region, inventories
only the three rehearsal EKS names, summarizes local Terraform state without
emitting attributes, and always leaves execution unauthorized.
Predecessor:
`v0.11.9.3.4-existing-image-aws-dev-promotion-execution` records successful
existing-image workflow run `34180004676`, reviewed values-only PR 71 and its
protected-main merge `071e32914a30`. aws-dev now declares the exact locally
qualified `sha-cf0a6bc` identity; aws-test/aws-prod remain unchanged. Main
validation and release orchestration succeeded, no image was rebuilt, and no
AWS runtime qualification is claimed.
Predecessor:
`v0.11.9.3.3.2-remote-successor-chain-repair` removes the remaining permanent
pre-promotion assumptions from the `.3.0` and `.3.3.1` validators. Both now
reuse the one exact aws-dev successor allowlist, while aws-test/aws-prod and
the rejection of `sha-6013688` remain strict. It changes no workflow or release
file and keeps PR 71 held for repaired-main validation.
Predecessor:
`v0.11.9.3.3.1-immutable-local-aws-successor-repair` makes the historical
local-only image validator accept the single reviewed aws-dev successor while
continuing to reject that identity from aws-test/aws-prod and rejecting the
incidental `sha-6013688`. It changes no release file or workflow and keeps PR
71 held until the repair reaches protected main.
Predecessor:
`v0.11.9.3.3-reviewed-main-integration` records protected-main merge commit
`6013688a384c`, keeps the locally qualified `sha-cf0a6bc` image as the only
allowed aws-dev successor, and rejects the incidental unqualified
`sha-6013688` promotion without changing release desired state or accessing
AWS. It repairs the historical release fingerprint so the selected successor
can pass later review while every other identity remains fail-closed.
Predecessor:
`v0.11.9.3.2-protected-main-integration-readiness` removes the temporary
aws-dev feature-revision override, restores every active AWS same-repository
Application to `main`, fingerprints unchanged release files and keeps remote
execution blocked until reviewed protected-main integration.
Predecessor:
`v0.11.9.3.1-existing-image-aws-dev-promotion` adds a protected-main-only,
manual handoff that verifies the original image run, metadata, GHCR digest,
SLSA provenance and SPDX SBOM before preparing a release-only aws-dev PR. It
cannot rebuild, deploy, access AWS/EKS or merge its PR; live dispatch remains
blocked until reviewed main integration.
Predecessor:
`v0.11.9.3.0-remote-release-rehearsal-design` pins the accepted `sha-cf0a6bc`
image for a protected-main, one-environment-at-a-time aws-dev/test/prod
rehearsal. It validates only an offline plan and blocks live execution until an
existing-image aws-dev release-PR handoff is implemented in v0.11.9.3.1.
Predecessor:
`v0.11.9.2.2.3.3.3.1-rendered-identity-projection-repair` separates the
container Downward API projection from successor AnalysisRun argument bindings,
removing a false global-count rejection without changing the Helm workload or
Healthy revision 70.
Predecessor:
`v0.11.9.2.2.3.3.3-baseline-restoration-closure` records the successful,
digest-pinned revision 70 baseline restoration, its two release-scoped
AnalysisRuns, final Argo CD convergence and an idempotent restore that created
no successor revision. It also removes a non-portable mawk quote escape.
Predecessor:
`v0.11.9.2.2.3.3.2-immutable-local-baseline-image` declares the image published
by workflow run `34070524953` as the digest-pinned local baseline and validates
its complete release identity before restoration.
Predecessor:
`v0.11.9.2.2.3.3.1-shellcheck-ci-parity` resolves the deterministic ShellCheck
failure that stopped workflow run `34035241036` before image build or push,
without changing restoration behavior or touching the cluster.
Predecessor:
`v0.11.9.2.2.3.3-request-series-image-compatibility` distinguishes target
readiness from request-series readiness, selects only post-observer
AnalysisRuns, and blocks the revision 69 rejected baseline image before restore.
Predecessor:
`v0.11.9.2.2.3.2-recovery-rollout-closure` records the successful local
revision 68 recovery, canonical kubectl plugin command ordering and the
observer-before-promote contract.
Predecessor:
`v0.11.9.2.2.3.1-successor-aware-target-query` preserves the historical
no-data contract while validating the current release-scoped target query.
Predecessor:
`v0.11.9.2.2.3-prometheus-identity-traffic-lifetime` waits for exact Prometheus
Candidate discovery and keeps bounded request traffic active through AnalysisRun
completion. See `docs/V0.11.9.2.2.3_PROMETHEUS_IDENTITY_TRAFFIC_LIFETIME.md`.
`v0.11.9.2.2.2.1.1-offline-lifecycle-environment-isolation` prevents ambient
local-kind or AWS shell variables from changing the fake aws-test lifecycle.
`v0.11.9.2.2.2.1-baseline-restoration-fixture-repair` updates the inherited
offline restoration fixture for the runtime-qualified success contract.
`v0.11.9.2.2.2-baseline-restoration-traffic-guard` separates GitOps sync from
runtime restoration and requires an armed bounded-traffic observer for each
SLO-aware AnalysisRun. See
`docs/V0.11.9.2.2.2_BASELINE_RESTORATION_TRAFFIC_GUARD.md`.
`v0.11.9.2.2.1-empty-digest-gitops-convergence-repair` omits the normalized
empty child fault-digest parameter, adds bounded exact-revision Root convergence
and preserves non-empty armed rendering. See
`docs/V0.11.9.2.2.1_EMPTY_DIGEST_GITOPS_CONVERGENCE_REPAIR.md`.
`v0.11.9.2.2-local-failure-recovery-live-qualification` adds read-only live
plan discovery, explicit operator checkpoints, redaction-safe progress output
and an exact final qualification summary. Applying or validating it performs no
live rehearsal. See
`docs/V0.11.9.2.2_LOCAL_FAILURE_RECOVERY_LIVE_QUALIFICATION.md`.
Predecessor:
`v0.11.9.2.1-local-failure-recovery-runner` implements a default-off,
local-only token-gated candidate availability fault, bounded stable/canary
traffic and explicit rejection/recovery phases. Producer checks are offline;
live execution is deferred. See
`docs/V0.11.9.2.1_LOCAL_FAILURE_RECOVERY_RUNNER.md`.
Predecessor:
`v0.11.9.2.0-local-failure-recovery-design` defines the offline-only,
candidate-scoped availability rejection and known-good GitOps restoration
contract. It implements and executes no fault. See
`docs/V0.11.9.2.0_LOCAL_FAILURE_RECOVERY_DESIGN.md`.
Predecessor:
`v0.11.9.1.1-local-release-rehearsal-stability` mirrors phase output live,
waits through bounded release Pod/imageID convergence and makes operator
handoffs, inputs, logs and retry boundaries explicit. It does not rerun or
expand the successful live rehearsal. See
`docs/V0.11.9.1.1_LOCAL_RELEASE_REHEARSAL_STABILITY.md` and the active runbook
`docs/V0.11.9.1_LOCAL_RELEASE_REHEARSAL.md`.
Predecessor:
`v0.11.9.1-local-release-rehearsal` adds explicit local deployment/analysis phases,
same-binary runtime identity checks and fresh Canary evidence. Live use is opt-in.
See `docs/V0.11.9.1_LOCAL_RELEASE_REHEARSAL.md`.
Predecessor:
`v0.11.9.0-release-rehearsal-design` defines release/failure/restoration scenarios
and an offline plan preflight; no runtime execution is authorized.
See `docs/V0.11.9.0_RELEASE_REHEARSAL_DESIGN.md`.
Predecessor:
`v0.11.8.4-multi-environment-closure` consolidates historical status and adds
local reviewed evidence archival, integrity checks and append-only baseline checks.
Prod live acceptance remains deferred. See `docs/V0.11.8.4_MULTI_ENVIRONMENT_CLOSURE.md`.
Predecessor:
`v0.11.8.3-prod-read-only-qualification` delivers a scoped-approval prod
observer and offline tests. Real prod deployment/acceptance is deferred to
the v0.11 tail; no prod live pass is claimed. See
`docs/V0.11.8.3_PROD_READ_ONLY_QUALIFICATION.md`.
Predecessor:
`v0.11.8.2.2-test-closure-and-rebuild` records the bounded historical aws-test
operator qualification and adds metadata-only Secret rebuild guards.
See `docs/V0.11.8.2.2_TEST_CLOSURE_AND_REBUILD.md`.
Predecessor:
`v0.11.8.2.1.3-test-target-identity` repairs stable/canary target recognition
with exact environment/release/Pod guards. See `docs/V0.11.8.2.1.3_TEST_TARGET_IDENTITY.md`.
Predecessor:
`v0.11.8.2.1.2-test-variable-input-repair` preserves reviewed local test tfvars,
checks runtime-role scope, and fingerprints inputs before saved-plan apply.
See `docs/V0.11.8.2.1.2_TEST_VARIABLE_INPUT_REPAIR.md`.
Predecessor:
`v0.11.8.2.1.1-active-gitops-preview-registration` aligns the historical gate
with the exact test preview and retains stable test/prod revision boundaries.
Predecessor:
`v0.11.8.2.1-aws-test-feature-qualification` adds separately guarded test
plan/apply/bootstrap and read-only exact-release observation. Read
`docs/V0.11.8.2.1_AWS_TEST_FEATURE_QUALIFICATION.md` before any live action.
Predecessor:
`v0.11.8.2.0.1-barman-chart-identity-render-coverage-repair` corrects the
Barman Application/Helm Chart identity and strengthens real-source coverage.
Validated predecessor:
`v0.11.8.2.0-aws-test-qualification-prerequisites` adds an offline-only test
preview and capacity/credential boundaries. No AWS resources are created.
See `docs/V0.11.8.2.0_AWS_TEST_QUALIFICATION_PREREQUISITES.md`.
Validated predecessor:
`v0.11.8.1.5-capacity-status-wait-closure` distinguishes operational capacity
warnings from failures, retains strict reserve mode, and adds a bounded node
readiness wait. See `docs/V0.11.8.1.5_CAPACITY_STATUS_WAIT_CLOSURE.md`.
Predecessor:
`v0.11.8.1.4-system-capacity-grafana-repair` adds an aws-dev four-node system
capacity budget and independent Grafana credentials. Prepare the Secret before
pushing the overlay; see `docs/V0.11.8.1.4_SYSTEM_CAPACITY_GRAFANA_REPAIR.md`.
It retains the earlier qualification checkpoint:
`v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification`.
It aligns every aws-dev same-repository child Application with the selected
feature revision for truthful pre-merge qualification, keeps other environments
and external Charts stable, and requires restoration to `main` before merge.
It retains `v0.11.8.1.1-observability-workflow-boundary-successor-repair`,
which repairs the historical workflow scanner while
retaining `v0.11.8.1-aws-dev-live-observability-qualification`, which
implements exact-identity, read-only aws-dev Prometheus, Grafana,
Alertmanager, rule, SLO, and declared-absence qualification while preserving
`v0.11.8.0-environment-observability-qualification-foundation`.
The foundation defines independent local, aws-dev, aws-test, and aws-prod qualification
profiles, exact environment/revision/release evidence identity, resumable
`waiting-runtime` semantics, and an approval-protected read-only production
boundary. It makes no live AWS qualification claim and retains
`v0.11.7.3.1-final-rollout-convergence-wait-repair`, which adds a bounded,
version-locked Healthy/stable ReplicaSet wait before final observability checks
while retaining
`v0.11.7.3-local-slo-progressive-delivery-closure`.
It unifies the four human-governed local release phases, final SLO evidence,
negative contracts, and retention boundaries before retaining
`v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair`.
It waits for the canary Service selector to resolve Ready Pods carrying the
exact new release ID and spreads bounded traffic across Prometheus scrapes
before retaining
`v0.11.7.2.1-slo-analysis-promql-and-live-race-repair`.
It repairs the stable availability PromQL grouping, makes local traffic
generation wait for an exact application version, and documents the required
feature `TARGET_REVISION` before retaining
`v0.11.7.2-slo-aware-argo-rollouts-analysis`.
It retains the accepted `v0.11.7.1.3-burn-rate-rule-inventory-jq-repair` and
adds local candidate-release and stable-budget gates to Argo Rollouts while
preserving the human promotion pause and explicit rollback ownership.
It retains the accepted
`v0.11.7.1.2-grafana-dashboard-successor-live-validation-repair` and repairs
the final Prometheus rule-inventory jq program and missing-rule diagnostics.
It retains the accepted
`v0.11.7.1.1-alert-inventory-order-independence-repair` and makes the live
Grafana Dashboard assertion accept the six-panel `.7.1` successor.
It retains the accepted `v0.11.7.1-multi-window-burn-rate-alerts` runtime and
removes filesystem traversal order from the historical alert-inventory check.
It retains the accepted `v0.11.7.0-demo-api-sli-slo-error-budget-foundation`
and `.7.0.1` revision-alignment precondition, then adds paired-window
availability and latency error-budget alerts, recording rules, Runbooks, and
Dashboard views without changing the Rollout or application image.
The retained repair checkpoint is
`v0.11.7.0.1-immutable-feature-root-reconciliation-repair`.
It retains the accepted `v0.11.6.2.3-local-minimal-tracing-closure` and adds a
runtime-artifact preflight before its two live correlation runs.
The local profile deploys one private, bounded Loki Monolithic instance, an
Alloy DaemonSet for node-local `startup-apps` Pod logs, and a separate
one-replica Alloy Deployment for cluster Kubernetes Events. Event read
positions use a 256Mi local PVC so collector Pod replacement does not replay
the Kubernetes Event TTL window. The existing Grafana instance receives one
non-default, non-editable, proxy-mode Loki data source. Pod and Event streams
both preserve the exact six-label index contract. Loki storage remains
disposable and limited to a 2 GiB `emptyDir` with 24-hour retention. Dashboards
and AWS logging remain outside this increment. v0.11.6.2.0 adds application-
side W3C propagation, bounded HTTP/PostgreSQL spans, shared release identity,
and real log correlation while keeping OTLP export disabled. v0.11.6.2.1 now
adds one private traces-only OTel Collector Deployment and one repository-owned
Tempo 3.0.3 Monolithic Deployment with bounded disposable local storage. The
application export and Grafana integration were deliberately separate from
that runtime increment. v0.11.6.2.2 now enables the already accepted exporter
only in the local App-of-Apps, validates a real `/version` SERVER span and its
correlated Loki JSON record, and provisions a private Grafana Tempo data source
plus a Loki `TraceID` derived field. Trace identifiers remain outside Loki's
label index, and no application image rebuild is required. Repair
`v0.11.6.2.1.1` corrects only the synthetic acceptance client: OTLP/JSON trace
and span identifiers are now hexadecimal, HTTP rejection bodies remain visible,
and Tempo/Collector diagnostics are selected explicitly. It changes no runtime
resource and requires neither reconciliation nor an image rebuild. Its runtime
predecessor is
`v0.11.6.2.1-private-local-otel-collector-tempo-runtime`. Repair
`v0.11.6.1.2.1` co-schedules the Event-position claim and
its consumer Application for `WaitForFirstConsumer` storage, makes Argo CD
sync waits bounded, and repairs exact historical Application counting. See
`docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md` and
`docs/V0.11.6.1.2_KUBERNETES_EVENTS_GRAFANA_LOKI.md`.
Repair `v0.11.6.1.2.2` normalizes the temporary acceptance Event timestamp to
the six-digit UTC precision required by Kubernetes `MicroTime`; it changes no
deployed workload. See
`docs/V0.11.6.1.2.2_KUBERNETES_EVENT_MICROTIME_ACCEPTANCE_REPAIR.md`.
Closure `v0.11.6.1.3` composes the platform, Pod-log, Events, Loki, and
Grafana checks into one repeatable entrypoint, adds strict successful-path
Event cleanup, preserves accepted Loki history after source deletion, and
retains the version-specific `WaitForFirstConsumer` incident record. It changes
no deployed workload. See
`docs/V0.11.6.1.3_LOCAL_LOGGING_END_TO_END_CLOSURE.md`.
The active tracing runtime is documented in
`docs/V0.11.6.2.1_PRIVATE_LOCAL_OTEL_COLLECTOR_TEMPO_RUNTIME.md`; its accepted
application contract is
`docs/V0.11.6.2.0_DEMO_API_OPENTELEMETRY_TRACING_CONTRACT.md`.
The corresponding accepted checkpoint identifier is
`v0.11.6.2.0-demo-api-opentelemetry-tracing-contract`.
Its accepted logging predecessor checkpoint is
`v0.11.6.1.3-local-logging-end-to-end-closure`.
Its reconciliation predecessor checkpoint is
`v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair`.
Its accepted Pod-log predecessor checkpoint is
`v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair`.
Its runtime predecessor checkpoint is
`v0.11.6.1.0-structured-demo-api-logging-runtime`.
The architectural foundation remains
`v0.11.6.0-centralized-logging-minimal-tracing-foundation`.

This repository demonstrates a practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, Argo Rollouts, GHCR image publishing, Prometheus, and a small demo API service.

The repository now contains the completed local progressive-delivery and AWS
EKS baselines, isolated On-Demand and Spot application NodePools, a tag-scoped
AWS FIS drill, and a GitOps-managed CloudNativePG PostgreSQL persistence,
high-availability, S3 backup, point-in-time recovery, application integration,
and primary-failover baseline. Reusable CI quality gates protect both
pull-request validation and GHCR image publishing. Published application
images now carry a SHA tag, immutable OCI digest, structured source identity,
and GitHub build-provenance attestation. Successful main-branch builds now
turn that identity into a reviewable aws-dev GitOps promotion pull request.
The same immutable identity can then move only through the ordered
`aws-dev -> aws-test -> aws-prod` chain, with one target-scoped, reviewable PR
per transition and no direct cluster access from GitHub Actions. Cross-
environment movement now requires a fresh, reviewed source-release evidence
record, a separately reviewed source-runtime evidence record, target GitHub
Environment approval, and CODEOWNERS review. AWS test and production desired
state now use Argo Rollouts with ALB weighted target groups, canary-local Web
AnalysisRuns, and explicit manual progression. The same
governance boundary applies to environment-scoped rollback PRs.
Promoted values and live workloads now retain enough delivery metadata to
correlate source, build, Git promotion, Argo CD reconciliation, Pod image ID,
and the application-reported version. A manual rollback workflow can now
restore a previously reviewed, metadata-aware desired state through another
values-only pull request. The AWS environment now also enforces namespace and
admission guardrails plus default-deny NetworkPolicy isolation for application
and CloudNativePG data workloads, with explicit runtime-validated traffic
paths. AWS Secrets Manager, exact-secret IRSA, a namespaced External Secrets
Operator deployment, and an active ExternalSecret now provide the demo-api
PostgreSQL credential without committing the value to Git or Terraform state.
The v0.9 lifecycle now also defines a clean-room aws-dev/aws-test acceptance
sequence, guarded ephemeral test creation, reviewed canary completion,
CloudNativePG recovery validation, dependency-aware test destruction, exact
AWS residual-cost checks, and tamper-evident final closure evidence. The
repository remains intentionally smaller than a full production platform.
The v0.8 finalization added the `demo.dev.aureumstack.com` Route 53 endpoint,
ACM-backed HTTPS, HTTP redirection, a runtime-only EKS management `/32`, and
bounded security logging. v0.9 turns this single live AWS baseline into a
cost-aware, multi-environment GitOps promotion model without requiring three
permanently running portfolio clusters. v0.9.7 separates disposable
control-plane logging cost from formal production-parity validation and makes
the cleanup audit aware of terminal Karpenter Instant Fleet history. v0.9.8
provides one canonical, command-by-command operator Runbook for GitHub setup,
evidence collection, ordered Promotion, safe pause/resume, and cost cleanup.
v0.10.0 now defines the deterministic, environment-independent release
identity, derived phase/status model, resumable transition graph, and separated
GitHub-hosted, trusted-runtime, and human approval boundaries that the later
delivery automation increments must implement. This checkpoint is deliberately
offline: it adds no release orchestrator and grants no Workflow AWS/EKS access.
v0.10.1 upgrades the existing image, static qualification, ordered Promotion,
and rollback workflows into reusable delivery stages with typed inputs,
machine-readable outputs, an offline stage contract, and unchanged manual
entrypoints. The reusable stages remain GitHub-hosted, PR-oriented, and unable
to access AWS or EKS; runtime qualification remains reserved for the later
trusted executor.
v0.10.2 adds the event-driven, read-only release orchestrator. Protected-main
source, release, and evidence events plus manual `start`, `status`, and `resume`
now produce a deterministic snapshot and next-action decision, discover and
reuse matching open PRs, reject ambiguous duplicates, and block safely if
`main` changes during derivation. This checkpoint remains plan-only: it grants
no write, AWS, or EKS permission and does not dispatch a reusable stage.
v0.10.3 implements the separately trusted runtime qualification boundary for
`aws-dev` and `aws-test`: protected-main preflight, environment-labeled
ephemeral self-hosted execution, short-lived GitHub OIDC, exact-cluster IAM,
namespaced read-only EKS RBAC, release-bound live checks, and a secret-free
temporary result artifact. It is not yet dispatched by the orchestrator and
does not implement production runtime access.
v0.10.3.1 repairs the dev/test-only RBAC Application assembly so standard
Kustomize load restrictions render every AWS overlay successfully, and brings
the runtime identity module into canonical Terraform formatting. No execution
or authorization boundary changes in this patch release.
v0.10.3.2 bounds trusted-runtime offline mutation-test storage by excluding
local Terraform caches, state, plans, and real variable files from temporary
repository copies, while retaining dependency lock and tracked configuration
files. It changes no runtime or authorization behavior.
v0.10.4 activates repository-variable-gated aws-dev qualification after a
reviewed dev release reaches `main`. It combines same-run static and trusted
runtime results into one scope-bound, self-contained Qualification Bundle PR,
waits passively for GitOps convergence, and stops before aws-test Promotion.
It neither rebuilds the image nor merges a PR, creates a cluster, syncs Argo
CD, accesses production, or dispatches rollback.
v0.10.5 consumes the merged, still-fresh aws-dev Bundle to prepare a reviewed
dev-to-test release-only PR. After that PR is merged, aws-test Canary progression
remains an explicit human action; only a manual `reviewed-and-completed` resume
may run same-run static/runtime qualification and create the reviewed aws-test
Bundle PR. v0.10.6 consumes that merged, still-fresh test Bundle to prepare a
reviewed test-to-prod release-only PR behind the protected `aws-prod` GitHub
Environment. The workflow never merges the PR, obtains production runtime
access, or writes Kubernetes.
v0.10.7 hardens recovery: manual `status` is now strictly read-only, `retry`
accepts only the exact prior safely retryable Attempt, newer Releases supersede
older unfinished work without automatically closing PRs, Bundle expiry and
drift are explicit, and selected dev/test runtime failures can produce a
read-only governed rollback handoff. The orchestrator still never dispatches a
rollback, merges a PR, or gains production runtime access.
v0.10.8 closes the version line with a protected-main clean-room acceptance
contract, exact dev/test/prod-static Runbook, interruption and environment
restoration checkpoints, deterministic expiry/retry/rollback-handoff tests,
dependency-aware dev/test cost cleanup, and repository-bound append-only final
evidence. The interruption checkpoint is a bounded post-runtime/pre-Bundle
hold, and final evidence rejects an interrupted/resumed pair that reused the
same registered self-hosted `runner_id` or left either runner registered. No
success evidence is included before the real live sequence runs.
v0.10.8.3 repairs the live rollback boundary discovered during that sequence:
the required currentness gate now distinguishes a workflow-proven historical
rollback from a superseded ordinary Promotion without trusting a branch prefix
alone, and the final Runbook provides the exact operator commands and evidence
mapping for the close-without-merge rollback drill.
v0.10.8.4 repairs the live cleanup boundary: interrupted destroys can continue
after EKS is already absent, Karpenter Instant Fleet request records are
retired, and exact EC2 checks distinguish active cost-bearing resources from
eventually consistent tag history. Final acceptance now captures each passing
cleanup audit's actual UTC timestamp with executable commands.
v0.10.8.5 completes the operator evidence mapping before closure: every
checkpoint now identifies the exact workflow run and PR to record, Release PR
A is distinguished from selected Release PR B, and the final input has
executable current-main, UTC timestamp, and placeholder/zero-value preflight
commands.
v0.10.8.6 fixes the final closure lifecycle so an empty directory is accepted
before chapter 17 and a proposed or committed final JSON is fully validated
during the evidence-only PR instead of being rejected merely for existing.
v0.10.8.7 is the post-tag image-security hotfix: closure tags no longer rebuild
demo-api, Debian fixable security updates are installed before publication,
Trivy v0.74.0 behavior is reproducible locally and in CI, and sealed v0.10
evidence is replayed against its recorded historical control plane.
v0.11.0 begins the Observability and SRE line with an environment-aware design
contract, stable telemetry and release-correlation conventions, an extensible
OpenTelemetry foundation, explicit cost and security profiles, and preserved
human production controls. It deploys no monitoring component and changes no
v0.10 acceptance evidence or release-orchestration behavior.
v0.11.1 replaces the active hand-written local Prometheus deployment with a
pinned Prometheus Operator metrics foundation and adds cost-aware AWS
dev/test/prod declarations. The stack includes Prometheus,
kube-state-metrics, node-exporter, bounded retention, encrypted gp3 storage,
explicit scrape NetworkPolicy, and compatibility with the existing local
Canary query. Grafana, Alertmanager, logs, tracing, SLOs, and telemetry-based
release gates remain later v0.11 increments.
v0.11.2 moves demo-api discovery into its own Helm Chart and adds bounded HTTP
and PostgreSQL dependency metrics. Prometheus target labels now correlate each
selected Pod with its environment, application version, deterministic release
ID, source commit, and image digest without changing the accepted v0.10 build,
Promotion, rollback, or production-approval workflows. Dashboard, alerting,
logging, tracing, and SLO work remains deferred.
v0.11.3 adds a parameterized and reversible local feature-revision GitOps
workflow. It prevents Root self-heal from silently returning same-repository
children to `HEAD`, verifies the deployed revision, Chart, ServiceMonitor and
Prometheus address, preserves manual Canary progression, and restores the
stable automated `HEAD` declaration after testing.
v0.11.4.1.1 provisions immutable Delivery, Data, and Platform Grafana
Dashboards from the accepted controller and dependency recording rules. Local
acceptance requires delivery, demo-api dependency, and platform rule data while
explicitly allowing CloudNativePG panels to remain no-data outside the AWS
profile.
v0.11.4.2.0 adds the capacity and resource-efficiency signal layer without a
new exporter, cost system, Dashboard, or automation action.
v0.11.4.2.1 adds the immutable Capacity and Resource Efficiency Dashboard and
consumes all twenty accepted rules without raw metric, scheduler-exact,
currency-cost, or automation claims. v0.11.4.2.2 repairs the clean replay with
a mandatory fresh local image transition, numeric target-health assertions,
shared bounded telemetry preflight, and Prometheus scrape diagnostics. The
accepted replay closes v0.11.4.
v0.11.5.0 enables one private environment-local Alertmanager per monitoring
profile with bounded storage and resources, stable critical and warning
routing, alert-family inhibition, and Prometheus discovery validation. It adds
no alert rule, external notification integration, central Alertmanager, or HA
claim; actionable alerts and Runbooks remain v0.11.5.1 work. The clean-room
v0.11 acceptance remains the final v0.11.9 increment.
v0.11.5.0.1 repairs the live acceptance check after Alertmanager serialized
`severity = "critical"` as the equivalent canonical `severity="critical"`.
It preserves exact route and inhibition cardinality and requires no runtime
redeployment. Its accepted checkpoint identity is
`v0.11.5.0.1-matcher-normalization-repair`.
v0.11.5.1 adds an exact eight-alert inventory for application, dependency,
delivery, Kubernetes workload, and AWS-profile PostgreSQL collection health.
Every alert has stable routing labels and one version-controlled Runbook; the
clean local baseline must load all rules while keeping them inactive. Its
accepted checkpoint identity is `v0.11.5.1-actionable-alerts-runbooks`.
v0.11.5.1.1 repairs `platform:prometheus_targets_down:count` with
`up == bool 0`, adds `PrometheusTargetDown` as the ninth alert, and introduces
a live recorded-versus-direct query cross-check without deliberately failing
a real target. Its checkpoint identity is
`v0.11.5.1.1-prometheus-target-down-semantics-repair`.
v0.11.5.1.1.1 corrects the live check to use
`operator-diagnostic-recording-rules` and restores the already-required fresh
image transition after the neutral pre-merge baseline. Its accepted checkpoint
identity is `v0.11.5.1.1.1-local-acceptance-path-repair`.
v0.11.5.2.0 proves the complete local alert lifecycle with temporary synthetic
signals and an internal-only webhook sink. Dedicated drill routes continue
into the existing critical and warning routes, resolved payloads are required,
critical-over-warning inhibition is checked in both equal and unequal scopes,
and every temporary object must be removed. External provider delivery and AWS
live execution remain deferred. Its predecessor checkpoint identity is
`v0.11.5.2.0-alert-lifecycle-drill`.
v0.11.5.2.0.1 repairs only the runtime configuration parser after the first
local attempt observed two correctly loaded webhook integrations whose URLs
were rendered as `url: <secret>`. It preserves exact literal desired-state URL
validation and requires no monitoring redeployment. Its predecessor checkpoint
identity is `v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair`.
v0.11.5.2.0.2 repairs the subsequent resolved-delivery phase by explicitly
transitioning each synthetic alert to an empty result before cleanup. Rule
deletion is no longer treated as the state transition, and reruns reject any
active drill alert left in Alertmanager by an earlier failed attempt. Its
predecessor checkpoint identity is
`v0.11.5.2.0.2-alert-resolution-transition-repair`.
v0.11.5.2.0.3 repairs the final cleanup synchronization boundary. After strict
Kubernetes deletion, the drill waits until both temporary alert definitions
disappear from the Prometheus rule inventory before requiring the exact nine
healthy inactive formal alerts. The repaired full local rerun passed, closing
v0.11.5 locally. Its accepted checkpoint identity is
`v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair`.
v0.11.6.0 defines environment-isolated logging and minimal tracing contracts.
v0.11.6.1.0 implements the first application runtime slice: bounded JSON Lines,
one process formatter, quiet successful probes, and Downward API projection of
release identity. v0.11.6.1.1 adds the private local Loki and Alloy Pod-log
path with bounded storage, resources, RBAC, NetworkPolicy, and label
cardinality. v0.11.6.1.2 adds singleton Kubernetes Event collection with
durable read positions and a Git-provisioned Grafana Loki data source; tracing
remains v0.11.6.2 scope.

## Current Version

```text
v0.12.2.2.1-bootstrap-state-migration-recovery-evidence
```
v0.12.2.2.1 records protected-main and private-result digest bindings for the
completed read-only identity-rebase recovery. It publishes only safe hashes,
counts, timestamps and booleans, adds no live authority and hands remote-state
proof to v0.12.2.3. See
`delivery/contracts/v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.json`.

The predecessor v0.12.2.2.0.2 corrects the recovery digest encoder to hash sorted compact JSON
with the same single trailing LF used by all reviewed incident digests. The
failed verification ran no operational command and found no state drift. This
repair adds no live authority and requires a new request and window. See
`delivery/contracts/v0.12.2.2.0.2-identity-rebase-digest-encoding-repair.json`.

The predecessor v0.12.2.2.0.1 binds the exact successful-init/identity-rebase incident and
accepts only the observed remote identity change when addresses, resources,
outputs and the semantic state projection remain exact. Its separately
approved executor resumes only state pull/list and S3 object-version reads by
using the existing backend metadata. It cannot reinitialize or remigrate state,
plan, apply, state-push, destroy, retry or roll back. Applying the package runs
no live command. See
`delivery/contracts/v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.json`.

The predecessor v0.12.2.2 binds a command-free verification and separately
approved single execution to the human-reviewed v0.12.2.1 private artifacts.
Its migration executor remains historical incident evidence and must not be
retried. See
`delivery/contracts/v0.12.2.2-reviewed-bootstrap-state-migration.json`.

The predecessor v0.12.2.1 binds command-free verification and the separately approved
read-only preflight to the exact private plan/apply/recovery evidence chain.
It declares only an empty partial S3 backend, creates a third private immutable
state copy and produces a reviewed command plan; it does not execute Terraform
init, plan, apply, state push, destroy or migration. See
`delivery/contracts/v0.12.2.1-private-bootstrap-migration-preflight.json`.

The predecessor v0.12.2.0.1 binds the future migration source to the original private plan-
bundle `source/terraform.tfstate` and its byte-identical preserved apply copy.
It explicitly rejects the unused repository-root state path as a fallback and
requires v0.12.2.1 to revalidate the complete private plan/apply/recovery
chain before any command. No state is copied, moved or migrated. See
`delivery/contracts/v0.12.2.0.1-private-bootstrap-state-location-repair.json`.

The predecessor v0.12.2.0 freezes the first migration to the non-empty 13-address bootstrap
state and its isolated `bootstrap/terraform.tfstate` key. It requires a private
immutable local backup, lineage/serial/address/resource-identity comparison,
zero-change plan, S3-native lock contention and separately approved object-
version recovery. The four historical roots remain local and retain their
reviewed Terraform floors. This checkpoint adds no backend declaration or live
authority. See
`delivery/contracts/v0.12.2.0-state-migration-design-foundation.json`.

The predecessor v0.12.1.2.1 binds the exact incident and recovery protected-
main commits, private artifact digests, applied local-state digest, reviewed-
plan counts and terminal live S3/KMS/IAM control results. The state-bootstrap
foundation was created and recovered without a second apply; its state remains
private and local, the state bucket remains empty, and no policy attachment or
migration occurred. That evidence adds no live authority. See
`delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json`.

The predecessor v0.12.1.2.0.1 repairs future KMS rotation-status reads to use
the exact key ARN and provides a fail-closed, read-only continuation after a
successful apply whose live validation stopped on the unsupported alias. It
never repeats Terraform apply or mutates state. v0.12.2 alone owns migration.

The predecessor v0.12.1.2 must merge before the fresh state-bootstrap plan is
produced. It binds one separately approved apply to the exact protected main, private plan
request, saved binary plan, JSON/text views, gate, source manifest, Terraform
version and expected AWS account. It can apply only that plan once, then
validates the 13-address local state plus the encrypted, versioned, public-
blocked and empty S3 foundation, rotating customer KMS key, and five unattached
IAM policies. It cannot initialize a backend, replan, destroy, migrate state or
attach a policy. v0.12.1.2.1 records the completed redacted execution evidence,
and v0.12.2 owns all state migration and recovery. See
`delivery/contracts/v0.12.1.2-reviewed-state-bootstrap-apply.json`.

The completed v0.8 AWS EKS environment exposes demo-api through
`https://demo.dev.aureumstack.com` with the production-security baseline in
place. v0.9.0 converges every active aws-dev repository Application on `main`
and establishes the formal `aws-dev -> aws-test -> aws-prod` design contract.
Each AWS environment maps to its own EKS cluster and isolated stateful
resources. v0.9.1 separates
stable Helm environment configuration from promotable release identity for
aws-dev, aws-test, and aws-prod. v0.9.2 adds independent Terraform roots and
states plus a shared Kustomize base with dev/test/prod overlays. All three
declarations are statically validated. v0.9.3 adds main-sourced, stale-state
protected environment Promotion PRs that retain the exact image digest and
source commit while changing only the target release file. v0.9.4 requires a
reviewed, unexpired evidence record that matches the current source release,
adds CODEOWNERS and target-environment approvals, and generalizes rollback to
aws-dev, aws-test, and aws-prod. v0.9.5 adds test/prod ALB canary declarations,
Argo Rollouts, release-bound AnalysisRuns, local collection of reviewed AWS
runtime evidence, and a dual static/runtime Promotion gate. v0.9.6 adds the
guarded clean-room aws-test lifecycle, recovery drill sequence, cost-residual
audit, and final evidence contract. The live sequence completed aws-dev and
aws-test validation plus the governed aws-test to aws-prod Promotion, while
aws-prod remained statically validated by design. v0.9.7 defaults disposable
dev/test control-plane ingestion off, provides an explicit all-five-log
production-parity checkpoint, preserves the live profile during management-IP
updates, and ignores only terminal or expired Instant Fleet history after
exact cost-resource checks pass. v0.9.8 closes the manual-operability
documentation gap with a single release procedure that distinguishes GitHub
workflow run IDs from UTC runtime-evidence IDs, corrects the Promotion input
name, and documents how a destroyed aws-test cluster can remain a valid source
for time-bounded static production Promotion.
v0.10.0 converts that validated manual procedure into a machine-readable
application contract and release-state schema. It fixes the only successful
phase path, treats absent environments and unavailable runtime executors as
resumable waits, preserves manual production approval and merge, and includes
offline negative tests for unsafe policy mutations. Workflow implementation,
OIDC/IAM/RBAC, and live runtime orchestration remain later v0.10 increments.
v0.10.1 adds `workflow_call` interfaces to the four existing delivery
workflows, publishes stable stage outputs, and records their script primitives,
mutation scopes, allowed environments, and security boundary in
`delivery/contracts/demo-api-stages.json`. It preserves all v0.9 dispatch and
push paths and does not introduce an orchestrator, automatic merge, or cluster
access.
v0.10.2 introduces `.github/workflows/demo-api-release-orchestrator.yaml`, a
read-only fact collector, and a deterministic planner. The orchestrator derives
one state and recommendation from current release files, matching evidence,
open PR contents, environment availability, and protected-main freshness. Its
workflow artifacts are diagnostic observations rather than mutable release
state. Actual stage dispatch remains deferred to v0.10.4 through v0.10.6, after
the v0.10.3 trusted runtime boundary exists.
v0.10.3 adds `.github/workflows/demo-api-runtime-qualification.yaml`, the
runtime executor/result contracts, short-lived OIDC access, GitOps-managed
read-only Roles, and deterministic runtime collection. The v0.10.8 clean-room
repair separates persistent account-bootstrap runtime IAM roles from
environment-owned EKS access entries, so an absent disposable environment is
distinguished from OIDC failure before cluster creation. An unavailable runner
or absent environment remains a safe wait; no GitHub-hosted fallback or
automatic Terraform apply is allowed.
The temporary runtime result becomes unified qualification evidence in
v0.10.4.
v0.10.4 adds deterministic qualification-scope hashing, same-run artifact
binding, a reviewed append-only aws-dev Bundle, and the single authorized
`qualify-aws-dev` orchestrator action. The explicit repository variable keeps
the action disabled while disposable AWS environments and ephemeral runners
are absent. After the Bundle merges, the planner recommends test Promotion but
does not dispatch it.
v0.10.5 activates that reviewed dev-to-test PR preparation behind
`DEMO_API_AWS_TEST_PROMOTION_ENABLED`, retains the existing guarded Canary
completion helper, and gates aws-test qualification separately with
`DEMO_API_AWS_TEST_QUALIFICATION_ENABLED`. Both automated paths accept only
protected-main facts; no PR is merged automatically.
v0.10.6 activates reviewed test-to-prod PR preparation behind
`DEMO_API_AWS_PROD_PROMOTION_ENABLED`. The job consumes only the current fresh
aws-test Qualification Bundle, enters the protected `aws-prod` Environment,
and may change only the aws-prod release values file. Production runtime access,
cluster creation, Kubernetes writes, rollback, and automatic merge remain
forbidden.
v0.10.7 adds secret-free short-retention Attempt artifacts, exact new-run retry
lineage, source-ancestry Release supersede, `fresh/expiring/expired/scope_drift/
release_drift/invalid` Bundle states, a one-hour Promotion validity floor, and
an optional manual dev/test rollback handoff. `status` can no longer dispatch
even when activation variables are enabled. All PR closure, merge, rollback,
Kubernetes mutation, environment creation, and production runtime operations
remain human or explicitly out of scope.
v0.10.8 adds `docs/V0.10_FINAL_ACCEPTANCE_RUNBOOK.md`, a machine-readable final
acceptance contract, strict closure-evidence schema/writer/validator, and an
offline negative gate that rejects unsafe production claims or incomplete
cleanup. Its clean-room repair also documents exact supersede/approval ordering
and Release ID derivation while moving trusted runtime roles into an
independent `runtime-identities` state. Live run IDs, PR numbers, Qualification
Bundles, and cleanup times are recorded later through one reviewed evidence-only
PR. The final tag is created only after that record merges; aws-prod remains
desired-state-only.

## Platform Architecture

```text
                         GitHub Repository

                                  |
                                  v

                               Argo CD

                         GitOps Control Plane

                                  |
                                  v

                      Kubernetes Applications

                                  |
                                  v

                         Application Delivery

                    - Helm
                    - Argo Rollouts


                                  |
                                  v

                          demo-api Workload



                 +----------------+----------------+

                 |                                 |

                 v                                 v


        Local Kubernetes Environment       AWS Kubernetes Environment


                 kind                         Amazon EKS


                  |                               |


          ingress-nginx              AWS Load Balancer
                                     Controller


                  |                               |


          Local Ingress                     AWS ALB
```

Both environments use Git and Argo CD as the desired-state control plane.
The local environment focuses on progressive delivery, while the AWS
environment covers cloud infrastructure, AWS-native application delivery,
dynamic capacity, and the CloudNativePG database control plane.
The diagram shows the aws-dev Deployment path. aws-test and aws-prod replace
the single workload/Service hop with an Argo Rollout, stable/canary Services,
ALB weighted target groups, and a release-bound AnalysisRun.

## Deployment Options

### Local GitOps Environment

Use the local environment for fast iteration, GitOps validation, and
progressive-delivery experiments.

See `docs/LOCAL_DEPLOYMENT.md`.

### AWS EKS Environment

Use the AWS environment for Terraform-managed infrastructure, Amazon EKS,
Argo CD bootstrap, AWS-native ingress, and cloud validation.

See `docs/AWS_EKS_DEPLOYMENT.md`.

## Repository Structure

```text
startup-devops-baseline/
├── .github/
│   └── workflows/
├── apps/
│   └── demo-api/
├── clusters/
│   ├── local/
│   └── aws/
│       ├── base/
│       └── overlays/{dev,test,prod}/
├── infra/
│   └── terraform/aws/
│       ├── modules/
│       └── environments/{dev,test,prod}/
├── docs/
├── delivery/
│   └── contracts/
├── evidence/
│   └── demo-api/
├── examples/
├── platform/
└── scripts/
```

## Documentation

### Architecture

- `docs/ARCHITECTURE.md`
- `docs/AWS_EKS_ARCHITECTURE.md`
- `docs/ENVIRONMENT_MODEL.md`
- `docs/MULTI_ENVIRONMENT_GITOPS_MODEL.md`
- `docs/V0.11_OBSERVABILITY_SRE_DESIGN.md`

### Deployment and Operations

- `docs/MULTI_ENVIRONMENT_RELEASE_RUNBOOK.md`
- `docs/LOCAL_DEPLOYMENT.md`
- `docs/AWS_EKS_DEPLOYMENT.md`
- `docs/AWS_EKS_DESTROY_RUNBOOK.md`
- `docs/AWS_PROGRESSIVE_DELIVERY.md`
- `docs/TROUBLESHOOTING.md`

### GitOps and Delivery

- `docs/RELEASE_ORCHESTRATION_MODEL.md`
- `docs/REUSABLE_DELIVERY_STAGES.md`
- `docs/RELEASE_ORCHESTRATOR.md`
- `docs/CI_IMAGE_WORKFLOW.md`
- `docs/DELIVERY_TRACEABILITY.md`
- `docs/GITOPS_ROLLBACK.md`
- `docs/GITOPS_WORKFLOW.md`
- `docs/PROMOTION_GOVERNANCE.md`
- `docs/V0.7_FINAL_VALIDATION.md`
- `docs/GHCR_IMAGE_WORKFLOW.md`
- `docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md`

### Terraform

- `docs/TERRAFORM_OUTPUTS.md`
- `docs/TERRAFORM_STATE_MANAGEMENT.md`

### Project Evolution

- `CHANGELOG.md`
- `docs/ROADMAP.md`
### v0.11.9.3.6.6.2 historical checkpoint CI decoupling

The protected-main readiness checkpoint now preserves its historical evidence
while delegating the mutable aws-test release to the reviewed successor
validator. Production remains byte-for-byte pinned until its own promotion.
See `docs/V0.11.9.3.6.6.2_HISTORICAL_CHECKPOINT_CI_DECOUPLING.md`.
### v0.11.9.3.6.6.3 successor policy convergence

All remaining main-CI checkpoints that inspected mutable aws-test release bytes
now delegate to the reviewed successor policy. Historical evidence remains
immutable and aws-prod remains pinned pending separate promotion.
### v0.11.9.3.6.6.4 aws-test promotion execution evidence

PR #91 completed the reviewed release-only aws-dev to aws-test Git handoff.
The immutable release identity is now equal in dev and test while production
remains unchanged. No live environment operation is authorized by this record.
### v0.11.9.3.6.6.5 aws-dev teardown preflight

A dedicated read-only preflight now verifies the exact main commit, AWS
identity, single active aws-dev cluster, Terraform ownership, and backup-bucket
presence before any destructive approval can be requested.
### v0.11.9.3.6.6.5.1 guarded aws-dev teardown executor

The destructive aws-dev wrapper is now reachable through a guarded executor
that binds reviewed preflight evidence, exact main, a bounded UTC window, an
immediate matching preflight, and a separate explicit approval.
### v0.11.9.3.6.6.5.2 aws-dev teardown execution evidence

The separately approved aws-dev teardown completed on exact protected main
`0a90e86ca844`. The immediate preflight matched its reviewed fingerprint, the
executor exited `0`, Terraform destroyed 90 resources, post-success dependency
convergence passed and Fleet retirement completed. The private preflight and
execution result remain outside Git and are pinned only by SHA-256. The first
missing-confirmation attempt is retained as a fail-closed, pre-AWS rejection.
No aws-test environment was created, no automatic retry ran, and the required
residual-cost audit remains a separate reviewed phase.
### v0.11.9.3.6.6.6 guarded aws-dev residual-cost audit

The post-teardown residual-cost sweep now has an exact-main, exact-account
guard with strict Terraform backend readability and zero-state checks. It
binds the `.5.2` teardown evidence and existing audit script by SHA-256,
requires no active rehearsal EKS environment, separates verify from one
explicitly approved execution and never retries automatically. Authoritative
bucket and secret listings prevent permission errors from masquerading as
absence. Raw AWS output stays in private `0600` files; the public result is
redacted. This checkpoint
implements and offline-tests the path but performs no live audit and does not
authorize aws-test creation.

### v0.11.9.3.6.6.6.1 aws-dev residual-cost audit execution evidence

The separately approved read-only audit completed once on exact protected
main `0ae04e26188a`. Its immediate preflight matched the reviewed result, the
executor and audit exited `0`, and no continuing cost identity was found.
Eight terminal or expired Fleet records were accepted as non-continuing
records. Private output remains outside Git and is represented only by
SHA-256, modes and byte counts; no account or resource identity is committed.
No mutation, automatic retry or aws-test creation occurred.

The aws-dev teardown and residual-cost audit chain is complete. The next phase
is a fresh, separately reviewed exact-main aws-test live-creation preflight,
plan and bounded execution window.

### v0.11.9.3.6.7 guarded aws-test live-creation preflight

The next environment now starts with a redacted exact-main readiness gate. It
binds the completed aws-dev audit and aws-test release-promotion evidence,
requires dev/test release equality with production held, confirms the expected
AWS account and zero active rehearsal EKS environments, and accepts only an
absent or valid empty aws-test local Terraform state. It runs no Terraform
command and explicitly forbids direct use of the historical plan-and-apply
wrapper. This implementation performs no live preflight or environment action.

### v0.11.9.3.6.7.1 guarded aws-test private creation-plan design

The successful `.6.7` preflight is now pinned by its redacted SHA-256 and exact
protected main. A new offline-only private-plan checker requires a later
post-merge main, a fresh preflight fingerprint, the immutable promoted release,
the current global management IPv4 and a fingerprint of the ignored local
Terraform variables. It enforces an eight-hour/USD 50 ceiling, one active
environment maximum, private `0700/0600` artifacts, one-hour plan review and a
nonempty create/read/no-op-only Terraform policy. This checkpoint runs no live
plan and leaves plan, apply and environment creation unauthorized.

### v0.11.9.3.6.7.2 guarded aws-test Terraform plan executor

The guarded plan path now has distinct local-only `verify` and separately
confirmed `execute` phases. It requires a clean post-implementation protected
main, a fresh byte-identical `.6.7` preflight, the populated owner-only `.7.1`
plan and unchanged reviewed repository inputs. Live execution is limited to
read-only account/environment/Secret metadata checks plus Terraform
init/plan/show. The saved private plan is machine-gated to a nonempty
create/read/no-op aws-test plan with exact variables and identities; updates,
deletes, replacements and unknown actions fail closed. Applying and validating
this checkpoint runs no AWS or Terraform command and authorizes neither plan
nor apply.

### v0.11.9.3.6.7.2.1 aws-test Terraform plan execution evidence

The separately approved plan-only execution completed on exact protected main
`845d918bbf27`. A byte-matched fresh preflight and zero-command executor verify
preceded Terraform init/plan/show. The private plan passed both the machine
gate and human review with 90 creates, six read-only lookups, one EKS cluster
and the expected Karpenter and runtime access entries. Secret metadata proved
the fixed name absent before and after planning. Apply, mutation and aws-test
creation did not occur. The plan expired after its one-hour review period and
cannot be reused; the next executor must require fresh post-merge evidence.

### v0.11.9.3.6.7.3 guarded aws-test Terraform apply executor

The create phase now has a local-only verify and separately confirmed execute
boundary. A post-merge protected main, fresh byte-identical preflight, new
private creation plan and unexpired saved plan are mandatory; the expired
`.7.2.1` plan is evidence only. Immediately before mutation, the executor
rechecks empty state, Secret absence and exact `terraform show -json` bytes,
then applies that saved plan once without replanning. Successful completion
requires reviewed state addresses, an ACTIVE aws-test EKS cluster and Secret
metadata, while GitOps, traffic and qualification remain separate. Applying
and validating this implementation performs no live operation.

### v0.11.9.3.6.7.3.1 aws-test state-classification repair

The reviewed `.7.3` saved plan applied successfully, but its post-apply state
gate rejected seven legitimate read-only data sources that were persisted in
state without appearing in `plan.resource_changes`. All 90 planned creates are
present and no additional managed address exists. A no-reapply resume executor
now binds the original private evidence and state, distinguishes managed and
data modes, and allows only the exact reviewed data types and counts. After a
new protected-main merge and local verify, a separately approved execution may
finish only STS, EKS and Secret metadata checks. It cannot run Terraform,
mutate AWS, bootstrap GitOps, generate traffic or qualify the environment.

### v0.11.9.3.6.7.3.1.1 aws-test apply and resume execution evidence

The exact human-reviewed saved plan was applied once on protected main
`1376129d42c`. Terraform succeeded, but the wrapper stopped in its post-apply
classifier because seven legitimate read-only data sources were not listed as
resource changes. The `.7.3.1` repair merged on `8b039bddbb56`, verified all 90
planned creates, zero missing creates and zero unexpected managed addresses,
then completed separately approved caller identity, EKS inventory/ACTIVE/API
boundary and credential-container metadata reads. It did not rerun Terraform
or mutate AWS. State and raw AWS output remain private and are represented only
by aggregate facts and SHA-256 fingerprints. GitOps bootstrap, traffic and
qualification remain unexecuted and require new post-merge controls.

### v0.11.9.3.6.7.4 guarded aws-test GitOps bootstrap

The next live checkpoint has an exact-main, separately reviewed two-phase
executor. Its preflight binds the `.7.3.1.1` evidence, private creation plan
and byte-identical live state; it allows only account, EKS, Secret metadata,
Terraform state/output and Kubernetes readiness/object reads. Execution must
bind the reviewed verify result and rerun the preflight before invoking the
shared EKS bootstrap exactly once. Success requires Argo CD core workloads,
two Terraform-derived IRSA annotations and the AWS Load Balancer Controller
Application while the aws-test Root Application remains absent. Terraform
mutation, Root deployment, traffic, qualification and retry are prohibited.

### v0.11.9.3.6.7.4.1 aws-test GitOps bootstrap execution evidence

The first verifier run stopped safely on a stale kubeconfig target. A private
AWS CLI dry-run kubeconfig then enabled a fresh successful verify, which was
separately reviewed and approved. The exact shared bootstrap ran once on
protected main `4aa621267676`, installed Argo CD `v3.5.2`, configured both
Terraform-derived IRSA ServiceAccounts and applied the AWS Load Balancer
Controller child Application. All post-checks passed, Terraform state remained
byte-identical, and the Root Application remained absent. One nonempty
bootstrap stderr line was independently classified as a warning with no
failure marker. Raw evidence and identities remain private.
