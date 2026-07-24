# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4, the
Karpenter AWS foundation introduced in v0.5.0, and the AWS FIS Spot
interruption foundation introduced in v0.5.5.

## Current scope: v0.5.5

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

Karpenter controller installation, `EC2NodeClass`, `NodePool`, and dynamic EC2
nodes remain GitOps-managed. Terraform owns the AWS identity and experiment
template used by the real interruption drill.

## Cost profile

After `terraform apply`, the main continuing costs are the EKS control plane,
EC2 managed nodes, NAT Gateway, EBS root volumes, and related network traffic.
Control-plane logging is disabled by default in the development environment to
avoid unnecessary CloudWatch ingestion charges.

## Validate locally

```bash
./scripts/validate-terraform.sh
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
```

Override `AWS_REGION` and `CLUSTER_NAME` when the environment uses different
values.
