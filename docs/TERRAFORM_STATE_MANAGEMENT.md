# Terraform State Management

## Current Design and v0.12 Boundary

The runtime-identities, dev, test, and prod Terraform roots each use their own
local state. This remains the implemented v0.12.0 state. The production
backend is defined by contract only and is not created until v0.12.1.

State files are excluded from Git. Keep them until the environment has been destroyed.

The saved plan created by `apply-eks-api-access-cidr.sh` is different from
state: it is a disposable, owner-readable execution artifact under `/tmp`, is
applied immediately, and is removed when the script exits. Losing that plan
before apply only fails the current run; it does not lose the deployed-resource
inventory. The local `terraform.tfstate` remains the authoritative artifact
that must be retained for the corresponding environment.

```text
infra/terraform/aws/runtime-identities/terraform.tfstate
infra/terraform/aws/environments/dev/terraform.tfstate
infra/terraform/aws/environments/test/terraform.tfstate
infra/terraform/aws/environments/prod/terraform.tfstate
```

Do not copy state between these directories and do not use Terraform CLI
workspaces to make one root impersonate another environment.

## Limitations

Local state does not provide centralized backup, locking, team access, controlled CI usage, or audit-friendly permissions.

## Target State Topology

v0.12 targets one independently addressable state object per root. A planned
account-scoped bootstrap root owns the backend infrastructure without making a
disposable EKS environment its dependency.

```text
bootstrap/terraform.tfstate
runtime-identities/terraform.tfstate
environments/dev/terraform.tfstate
environments/test/terraform.tfstate
environments/prod/terraform.tfstate
```

The target backend requires:

- S3 versioning;
- server-side encryption with a customer-managed KMS key;
- complete S3 public-access blocking and TLS-only access;
- S3-native lockfiles;
- root/key-scoped read, write and lock permissions;
- partial backend configuration without credentials in tracked files; and
- no Terraform CLI workspace sharing between environments.

## Bootstrap Boundary

The backend must exist before another root can initialize it. v0.12.1 therefore
creates a dedicated bootstrap boundary before changing any existing root. The
bootstrap state begins as a separately protected local artifact; migration of
that state into its own isolated key requires a later reviewed step and an
explicit backend-decommission Runbook.

## Migration and Recovery Invariants

v0.12.2 must use a non-empty reviewed state. An empty destroyed environment is
not accepted as migration evidence. The migration must preserve state lineage,
every managed address and every bound resource identity, and must finish with
a zero-change plan.

Backend migration must not be combined with:

- Terraform module or resource-address refactoring;
- import or replacement work;
- EKS or platform version upgrades; or
- application release promotion.

Before migration, retain an owner-readable local backup and its digest. After
migration, verify remote state bytes, lock contention, version history,
operator access boundaries and one controlled object-version recovery drill.
The local backup remains recovery evidence until the remote recovery gate is
accepted.

## Safety Rules

- Never commit state.
- Treat state as sensitive.
- Do not delete state before destroy completes.
- Do not apply obsolete saved plans.
- Keep saved plans short-lived and owner-readable because they can contain
  sensitive values even when terminal output redacts them.
- Back up state before risky refactoring.
- Never treat an empty-state migration as production-readiness evidence.
- Never combine backend migration with resource-address or platform changes.
- Never grant application delivery automation permission to create, migrate,
  recover, or destroy Terraform state.
