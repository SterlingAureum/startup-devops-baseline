# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4.

## Current scope

The initial skeleton establishes:

- a development environment entry point;
- separate VPC and EKS module boundaries;
- Terraform and AWS provider constraints;
- shared naming and default tagging inputs;
- local validation that does not require AWS credentials;
- GitHub Actions checks for formatting and configuration validity.

No AWS resources are created in this phase.

## Validate locally

From the repository root:

```bash
./scripts/validate-terraform.sh
```

Or run the commands directly:

```bash
terraform -chdir=infra/terraform/aws/environments/dev fmt -check -recursive
terraform -chdir=infra/terraform/aws/environments/dev init -backend=false
terraform -chdir=infra/terraform/aws/environments/dev validate
```

## Local variable file

Copy the example only when infrastructure planning begins:

```bash
cp infra/terraform/aws/environments/dev/terraform.tfvars.example \
  infra/terraform/aws/environments/dev/terraform.tfvars
```

`terraform.tfvars` is ignored by Git and must not contain credentials.
