# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4, the
Karpenter AWS foundation introduced in v0.5.0, the AWS FIS Spot interruption
foundation introduced in v0.5.5, the CloudNativePG S3 backup foundation
introduced in v0.6.3, the External Secrets AWS foundation introduced in
v0.8.3, and the ACM/control-plane hardening foundation introduced in v0.8.6.

## Current repository scope: v0.9.6

Terraform owns stable AWS infrastructure and identity. Argo CD owns the
Kubernetes controllers and application resources, while guarded scripts
coordinate runtime-only values such as the management `/32`, the ALB Alias,
and database credential transitions.

The dev, test, and prod directories are independent Terraform roots. They use
the same reviewed modules but never share local state or CLI workspaces. A
fourth account-bootstrap root, `runtime-identities`, owns the dev/test GitHub
OIDC runtime roles independently from disposable environment state. The
environment roots own only the corresponding EKS access entries.

| Profile | VPC | Service CIDR | Logs | Secret recovery | Backup destroy |
|---|---|---|---:|---:|---|
| dev | `10.20.0.0/16` | `172.20.0.0/16` | 14 days | immediate | allowed |
| test | `10.30.0.0/16` | `172.21.0.0/16` | 30 days | 7 days | allowed |
| prod | `10.40.0.0/16` | `172.22.0.0/16` | 90 days | 30 days | rejected |

Each applied environment creates:

- the v0.4.1 VPC network baseline;
- an Amazon EKS control plane in private subnets;
- one On-Demand EKS managed node group;
- cluster and node IAM roles;
- an IAM OIDC provider;
- an IRSA role for the EBS CSI controller;
- EKS managed VPC CNI, CoreDNS, kube-proxy, and EBS CSI add-ons;
- an optional EKS access entry for a long-lived administrator principal;
- a dedicated Karpenter controller IRSA role and scoped policies;
- a dedicated Karpenter node role and EKS access entry;
- an encrypted interruption queue and EventBridge rules;
- subnet and security-group discovery tags;
- an AWS FIS experiment role and tag-scoped template in dev/test only;
- a versioned, encrypted, public-access-blocked S3 backup bucket;
- a least-privilege IRSA role for PostgreSQL base backups and WAL archives;
- a Secrets Manager Secret container with no Terraform-managed value; and
- an External Secrets IRSA role scoped to read only that Secret;
- an environment-specific DNS-validated ACM certificate;
- a fail-closed EKS public endpoint allowlist supplied only at runtime; and
- security-relevant EKS control-plane logs with 14-day retention.

Karpenter controller installation, `EC2NodeClass`, `NodePool`, and dynamic EC2
nodes remain GitOps-managed. Terraform owns the AWS identity and experiment
template used by the real interruption drill. Terraform owns only the External
Secrets AWS foundation; the operator and secret synchronization remain
GitOps-managed.

## Cost profile

After `terraform apply`, the main continuing costs are the EKS control plane,
EC2 managed nodes, NAT Gateway, EBS root volumes, S3 backup storage and
requests, Secrets Manager storage and API calls, and related network traffic.
Security-relevant control-plane logging is enabled with environment-specific
bounded retention. The repository does not require the three clusters to run
at the same time: aws-test is ephemeral and aws-prod is statically validated
without a mandatory v0.9 apply.

## Validate locally

```bash
./scripts/validate-terraform.sh
./scripts/validate-external-secrets-foundation.sh
```

## Plan

`validate-terraform.sh` formats and validates the account-bootstrap root plus
all three environment roots with backend
initialization disabled. Do not put a workstation address in any tracked
tfvars. The guarded apply entrypoint currently defaults to dev:

```bash
CONFIRM_EKS_API_CIDR_UPDATE=restrict-current-ip \
  ./scripts/apply-eks-api-access-cidr.sh
```

It supplies the current `/32` only for the Terraform execution. EKS is pinned
to 1.36 for
compatibility with Karpenter 1.14.x. Review the complete plan because this
environment creates billable EKS and EC2 resources. Creating the dev/test FIS
template does not start an experiment. v0.9.6 requires one bounded aws-test
clean-room apply after the implementation reaches reviewed `main`; aws-prod
remains statically validated and must not be applied merely to close the
portfolio checkpoint.

Use the guarded test entrypoint rather than supplying a workstation address in
tracked configuration:

```bash
CONFIRM_AWS_TEST_APPLY=apply-ephemeral-aws-test \
  ./scripts/apply-aws-test.sh
```

After runtime and recovery validation, destroy the temporary environment and
require the residual audit to pass:

```bash
CONFIRM_AWS_ENVIRONMENT_DESTROY=destroy-aws-test-with-backups \
  ./scripts/destroy-aws-test.sh

AWS_ENVIRONMENT=aws-test \
  ./scripts/validate-aws-cost-cleanup.sh
```

See `docs/AWS_MULTI_ENVIRONMENT_LIFECYCLE.md` for the complete ordered
acceptance and safe continuation steps.

## Configure kubectl after apply

```bash
aws eks update-kubeconfig \
  --region us-east-1 \
  --name startup-devops-baseline-dev

kubectl get nodes
kubectl get pods -n kube-system
```

## Validate the running cluster

```bash
./scripts/validate-eks-baseline.sh
./scripts/validate-karpenter-foundation.sh
./scripts/validate-karpenter-fis.sh
./scripts/validate-cloudnative-pg-backup.sh
./scripts/validate-cloudnative-pg-recovery.sh
./scripts/validate-external-secrets-foundation-aws.sh
```

Override `AWS_REGION` and `CLUSTER_NAME` when the environment uses different
values.
