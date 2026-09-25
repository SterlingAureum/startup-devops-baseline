# Current Authoritative Surface

This index separates current supported material from historical implementation
records. It is introduced in v0.12.0 and will be fully converged during v1.0
RC. The index does not delete or rewrite historical evidence.

## Authority Classes

| Class | Meaning | Review rule |
| --- | --- | --- |
| Current architecture | Describes the supported platform and ownership boundaries. | Must match active code and declarations. |
| Current operation | Supported deployment, release, recovery and teardown procedure. | Must be validated against a current entry point. |
| Contract | Machine-readable safety, identity and acceptance boundary. | Must have deterministic positive and negative validation. |
| Evidence | Immutable record of a completed checkpoint. | Must not be rewritten to describe a later state. |
| Historical checkpoint | Explains how an earlier increment was implemented or repaired. | Retained for traceability; not a current procedure unless explicitly indexed. |
| Archive | Superseded material under `docs/archive/`. | Unsupported and must not be referenced by current entry points. |

## Current Architecture and Policy

- `README.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/AWS_EKS_ARCHITECTURE.md`
- `docs/TERRAFORM_STATE_MANAGEMENT.md`
- `docs/GITOPS_IMAGE_PROMOTION_MODEL.md`
- `docs/RELEASE_ORCHESTRATION_MODEL.md`
- `docs/PROMOTION_GOVERNANCE.md`
- `docs/AI_ASSISTED_CONTRIBUTION_POLICY.md`
- `docs/V0.12.0_PRODUCTION_READINESS_FOUNDATION.md`
- `docs/V0.12.1_REMOTE_STATE_FOUNDATION.md`
- `docs/V0.12.1.0.1_CI_COMPATIBILITY_REPAIR.md`
- `docs/V0.12.1.1_GUARDED_STATE_BOOTSTRAP_PLAN.md`
- `docs/V0.12.1.2_REVIEWED_STATE_BOOTSTRAP_APPLY.md`
- `docs/V0.12.1.2.0.1_STATE_BOOTSTRAP_POST_APPLY_RECOVERY.md`
- `docs/V0.12.1.2.1_STATE_BOOTSTRAP_EXECUTION_EVIDENCE.md`

These documents are current but not yet the final v1.0 commercial review. A
known stale statement in a current document is updated when its owning
capability changes; the repository-wide consistency pass remains v1.0 RC.1.

## Current Implementation Surface

- `.github/workflows/` for validated CI, release preparation and trusted
  runtime boundaries;
- `infra/terraform/aws/` for the five implemented independent roots, partial
  backend examples and shared AWS modules;
- `clusters/local/` and `clusters/aws/` for active GitOps declarations;
- `apps/demo-api/` for the demonstration workload and Helm release contract;
- `platform/` for repository-owned observability, tracing and security assets;
- `delivery/contracts/` for machine-readable contracts and evidence schemas;
- `scripts/` for validators and guarded operator entry points.

Directory inclusion does not make every historical file a supported operator
command. The v1.0 RC review will publish the smaller stable command surface.

## Current Release and State Contracts

- `delivery/contracts/demo-api-orchestrator.json`
- `delivery/contracts/demo-api-failure-recovery-policy.json`
- `delivery/contracts/v0.11-final-evidence-manifest.json`
- `delivery/contracts/v0.12.0-production-readiness-foundation.json`
- `delivery/contracts/v0.12.1-remote-state-foundation.json`
- `delivery/contracts/v0.12.1.0.1-ci-compatibility-repair.json`
- `delivery/contracts/v0.12.1.1-guarded-state-bootstrap-plan.json`
- `delivery/contracts/v0.12.1.2-reviewed-state-bootstrap-apply.json`
- `delivery/contracts/v0.12.1.2.0.1-state-bootstrap-post-apply-recovery.json`
- `delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json`

The v0.11 manifest remains authoritative only for v0.11 evidence claims. The
v0.12 contract cannot upgrade historical evidence or synthetic receipts into
live authority.

## Historical and Archive Rules

- `docs/V0.*` checkpoint documents are historical records unless explicitly
  listed above as current.
- `delivery/contracts/v0.*` checkpoint contracts remain immutable evidence of
  their own version unless a documented successor validator explicitly accepts
  a later state.
- `evidence/` and `artifacts/` retain scoped records; they are not generic
  production-readiness claims.
- `docs/archive/` is unsupported historical material. Current README,
  workflows, operator entry points and current Runbooks must not depend on it.
- Historical material is checked for privacy and reference safety, not rewritten
  line by line during v1.0 convergence.

## v1.0 RC Review Queue

The final commercial review is split into repository/demo/document convergence
in v1.0 RC.1, AI/license/security assurance in v1.0 RC.2, and the final
sequential dev/test/prod acceptance in v1.0 RC.3. It will:

1. freeze new technical capabilities after v0.12.7;
2. review current code, IaC, GitOps, workflows, operator scripts and documents
   according to risk;
3. publish stable supported, optional and out-of-scope surfaces;
4. converge README, architecture, deployment, operation and teardown guidance;
5. publish the supported-version and upgrade matrix;
6. complete AI, license, SBOM, provenance and security assurance; and
7. run the final sequential dev/test/prod commercial acceptance.
