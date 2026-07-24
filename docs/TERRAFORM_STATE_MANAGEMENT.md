# Terraform State Management

## Current Design

The `aws-dev` environment currently uses local state. This is acceptable for personal development, demonstrations, and a single operator.

State files are excluded from Git. Keep them until the environment has been destroyed.

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
startup-devops-baseline/staging/terraform.tfstate
startup-devops-baseline/prod/terraform.tfstate
```

## Bootstrap Boundary

The backend must exist before the main configuration can use it. A future design should separate backend bootstrap resources from the main VPC/EKS environment.

## Safety Rules

- Never commit state.
- Treat state as sensitive.
- Do not delete state before destroy completes.
- Do not apply obsolete saved plans.
- Back up state before risky refactoring.
