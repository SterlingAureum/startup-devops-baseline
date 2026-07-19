# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4.

## Current scope: v0.4.2

The development environment now creates:

- the v0.4.1 VPC network baseline;
- an Amazon EKS control plane in private subnets;
- one On-Demand EKS managed node group;
- cluster and node IAM roles;
- an IAM OIDC provider;
- an IRSA role for the EBS CSI controller;
- EKS managed VPC CNI, CoreDNS, kube-proxy, and EBS CSI add-ons;
- an optional EKS access entry for a long-lived administrator principal.

Karpenter, Spot worker pools, AWS Load Balancer Controller, Argo CD, and the
application deployment remain outside this phase.

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

Before applying, restrict `eks_public_access_cidrs` and decide whether to pin
`eks_cluster_version`. Review the complete plan because this phase creates
billable EKS and EC2 resources.

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
```

Override `AWS_REGION` and `CLUSTER_NAME` when the environment uses different
values.
