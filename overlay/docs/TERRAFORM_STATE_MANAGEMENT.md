# Terraform State Management

## Current Design

The dev, test, and prod Terraform roots each use their own local state in
v0.9.2. This is acceptable for single-operator, sequential portfolio
validation; it is not the long-term production backend model.

State files are excluded from Git. Keep them until the environment has been destroyed.

The saved plan created by `apply-eks-api-access-cidr.sh` is different from
state: it is a disposable, owner-readable execution artifact under `/tmp`, is
applied immediately, and is removed when the script exits. Losing that plan
before apply only fails the current run; it does not lose the deployed-resource
inventory. The local `terraform.tfstate` remains the authoritative artifact
that must be retained for the corresponding environment.

```text
infra/terraform/aws/environments/dev/terraform.tfstate
infra/terraform/aws/environments/test/terraform.tfstate
infra/terraform/aws/environments/prod/terraform.tfstate
```

Do not copy state between these directories and do not use Terraform CLI
workspaces to make one root impersonate another environment.

## Limitations

Local state does not provide centralized backup, locking, team access, controlled CI usage, or audit-friendly permissions.

## Production Direction

A later production version should use:

```text
S3 backend
S3 versioning
S3 native locking or an approved locking mechanism
Server-side encryption
Restricted IAM access
Separate state per environment
```

Example keys:

```text
startup-devops-baseline/dev/terraform.tfstate
startup-devops-baseline/test/terraform.tfstate
startup-devops-baseline/prod/terraform.tfstate
```

## Bootstrap Boundary

The backend must exist before the main configuration can use it. A future design should separate backend bootstrap resources from the main VPC/EKS environment.

## Safety Rules

- Never commit state.
- Treat state as sensitive.
- Do not delete state before destroy completes.
- Do not apply obsolete saved plans.
- Keep saved plans short-lived and owner-readable because they can contain
  sensitive values even when terminal output redacts them.
- Back up state before risky refactoring.
