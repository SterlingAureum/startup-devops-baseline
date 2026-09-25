# Terraform State Management

## Current Design and v0.12.1.2.1 Boundary

The runtime-identities, dev, test, and prod Terraform roots each use their own
local state. v0.12.1 adds the independent `state-bootstrap` root, which also
uses local state until migration. The S3/KMS foundation has now been created
and live-validated, but the bootstrap state remains a private local artifact
and the four existing runtime/environment roots remain on local state.

State files are excluded from Git. Keep them until the environment has been destroyed.

The v0.12.1.0.1 CI repair keeps the new state-bootstrap and future remote
backend minimum at Terraform 1.11 while restoring the four unchanged local
roots to their reviewed `>= 1.8.0` declarations. CI still validates all five
roots with Terraform 1.16.3. Before any v0.12.2 remote initialization, the four
existing declarations require a separate successor-compatible floor update;
that update and state migration must not share one execution window.

v0.12.1.1 adds a guarded plan-only entry point for the first state-bootstrap
create. It requires an absent local bootstrap state, exact protected main,
private owner-only request/tfvars files, a matching STS account and a bounded
approval. Its accepted plan contains exactly the 13 declared managed creates
and remains private. It never applies the plan or initializes an S3 backend.
The exact saved-plan apply and live foundation validation are owned by v0.12.1.2;
all state migration and recovery invariants remain v0.12.2.

v0.12.1.2 now implements that apply boundary offline. It must be merged before
the fresh v0.12.1.1 plan is produced so both plan and apply bind the same exact
protected-main revision. The executor can consume only the reviewed binary
plan, preserves the resulting bootstrap state under the private plan source,
and validates the live but empty S3/KMS/IAM-policy foundation. It cannot attach
the policies, configure a remote backend or migrate any state. Its completed
redacted live execution evidence is recorded by v0.12.1.2.1.

v0.12.1.2.0.1 repairs a post-apply validation defect without repeating the
successful bootstrap apply. `kms:GetKeyRotationStatus` now receives the exact
Terraform output key ARN instead of the alias. Its recovery entry point accepts
only the bound `InvalidArnException` incident, byte-identical working and
preserved state, the exact 13 managed addresses and unchanged plan/source
artifacts. Recovery performs only read-only S3/KMS/IAM validation; it cannot
run Terraform, mutate state, attach a policy, destroy resources or migrate a
backend.

v0.12.1.2.1 records the resulting redacted execution evidence. It binds the
exact reviewed-plan and private-request digests, matching applied-state digest,
incident/recovery protected-main revisions and terminal recovery/live-
validation digests. The foundation has now been created and live-validated:
the state bucket is still empty, the customer-managed KMS key is enabled with
rotation, and all five root-scoped policies remain unattached. This checkpoint
adds no executor and does not authorize backend initialization or migration.

The saved plan created by `apply-eks-api-access-cidr.sh` is different from
state: it is a disposable, owner-readable execution artifact under `/tmp`, is
applied immediately, and is removed when the script exits. Losing that plan
before apply only fails the current run; it does not lose the deployed-resource
inventory. The local `terraform.tfstate` remains the authoritative artifact
that must be retained for the corresponding environment.

```text
infra/terraform/aws/state-bootstrap/terraform.tfstate
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

v0.12 targets one independently addressable state object per root. The
account-scoped bootstrap root owns the declared backend infrastructure without
making a disposable EKS environment its dependency.

```text
bootstrap/terraform.tfstate
runtime-identities/terraform.tfstate
environments/dev/terraform.tfstate
environments/test/terraform.tfstate
environments/prod/terraform.tfstate
```

The declared target backend provides:

- S3 versioning;
- server-side encryption with a customer-managed KMS key;
- complete S3 public-access blocking and TLS-only access;
- S3-native lockfiles;
- root/key-scoped read, write and lock permissions;
- partial backend configuration without credentials in tracked files; and
- no Terraform CLI workspace sharing between environments.

Tracked examples live under `infra/terraform/aws/backend-config/`. Copy one to
an ignored `*.tfbackend` path and replace every placeholder only during an
approved migration. Never add credentials, a real account identity, a bucket
identity or a principal identity to the tracked examples.

## Bootstrap Boundary

The backend must exist before another root can initialize it. v0.12.1 therefore
declares a dedicated bootstrap boundary without changing any existing backend
declaration. The bootstrap state begins as a separately protected local
artifact; migration of that state into its own isolated key requires the
reviewed v0.12.2 procedure and an explicit backend-decommission Runbook.

The bootstrap root creates five exact state/lock IAM managed-policy
definitions, one for each root, but attaches none. The state object receives Get/Put only; its
`.tflock` companion receives Get/Put/Delete. Application delivery and the
existing GitHub runtime roles receive no state authority from v0.12.1.

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
