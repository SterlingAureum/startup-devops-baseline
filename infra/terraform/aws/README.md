# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4, the
Karpenter AWS foundation introduced in v0.5.0, the AWS FIS Spot interruption
foundation introduced in v0.5.5, the CloudNativePG S3 backup foundation
introduced in v0.6.3, and the External Secrets AWS foundation introduced in
v0.8.3.

## Current repository scope: v0.8.3 checkpoint 1

Checkpoint 1 creates the Secrets Manager container and least-privilege IRSA
identity that External Secrets Operator will use. It does not install the
operator or place a database credential in Secrets Manager.

The development environment now creates:

- the v0.4.1 VPC network baseline;
- an Amazon EKS control plane in private subnets;
- one On-Demand EKS managed node group;
- cluster and node IAM roles;
- an IAM OIDC provider;
- an IRSA role for the EBS CSI controller;
- EKS managed VPC CNI, CoreDNS, kube-proxy, and EBS CSI add-ons;
- an optional EKS access entry for a long-lived administrator principal.
- a dedicated Karpenter controller IRSA role and scoped policies;
- a dedicated Karpenter node role and EKS access entry;
- an encrypted interruption queue and EventBridge rules;
- subnet and security-group discovery tags;
- an AWS FIS experiment role with only the Spot interruption permissions;
- a tag-scoped, single-target Spot interruption experiment template.
- a versioned, encrypted, public-access-blocked S3 backup bucket;
- a least-privilege IRSA role for PostgreSQL base backups and WAL archives;
- a Secrets Manager Secret container with no Terraform-managed value; and
- an External Secrets IRSA role scoped to read only that Secret.

Karpenter controller installation, `EC2NodeClass`, `NodePool`, and dynamic EC2
nodes remain GitOps-managed. Terraform owns the AWS identity and experiment
template used by the real interruption drill. Terraform owns only the External
Secrets AWS foundation; the operator and secret synchronization remain
GitOps-managed.

## Cost profile

After `terraform apply`, the main continuing costs are the EKS control plane,
EC2 managed nodes, NAT Gateway, EBS root volumes, S3 backup storage and
requests, Secrets Manager storage and API calls, and related network traffic.
Control-plane logging is disabled by default in the development environment to
avoid unnecessary CloudWatch ingestion charges.

## Validate locally

```bash
./scripts/validate-terraform.sh
./scripts/validate-external-secrets-foundation.sh
```

## Plan

```bash
cp infra/terraform/aws/environments/dev/terraform.tfvars.example \
  infra/terraform/aws/environments/dev/terraform.tfvars

terraform -chdir=infra/terraform/aws/environments/dev init
terraform -chdir=infra/terraform/aws/environments/dev plan
```

Before applying, restrict `eks_public_access_cidrs`. EKS is pinned to 1.36 for
compatibility with Karpenter 1.14.x. Review the complete plan because this
environment creates billable EKS and EC2 resources. Creating the FIS template
does not start an experiment.

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
