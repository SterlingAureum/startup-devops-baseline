# AWS EKS Architecture

## Purpose

The `aws-dev` environment is a reproducible AWS EKS baseline that can be created with Terraform, bootstrapped with Argo CD, validated, exposed through ALB, and destroyed cleanly.

## Architecture

```text
                               GitHub
                                 │
                                 ▼
                              Argo CD
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
   AWS Load Balancer Controller             demo-api
                  │                             │
                  └──────────────┬──────────────┘
                                 ▼
                       Kubernetes Ingress
                                 ▼
                    Application Load Balancer
                                 ▼
                              Internet
```

Infrastructure ownership:

```text
Terraform
├── VPC and subnets
├── Internet Gateway and NAT Gateway
├── Amazon EKS
├── Managed Node Group
├── EKS managed add-ons
├── IAM roles and policies
└── OIDC provider

Bootstrap scripts
├── kubeconfig
├── Argo CD installation
└── IRSA ServiceAccount annotation

Argo CD
├── AWS Load Balancer Controller
└── demo-api
```

## Network

```text
VPC 10.20.0.0/16
├── Public subnet AZ-A  10.20.0.0/24
├── Public subnet AZ-B  10.20.1.0/24
├── Private subnet AZ-A 10.20.10.0/24
└── Private subnet AZ-B 10.20.11.0/24
```

Managed nodes run in private subnets. The development environment uses one shared NAT Gateway to reduce cost.

## Identity

```text
Human operator → AWS IAM → EKS access
Managed node → Node IAM role
EBS CSI controller → IRSA role
AWS Load Balancer Controller → IRSA role
```

## IMDS and VPC Discovery

Nodes use IMDSv2 with hop limit `1`. The AWS Load Balancer Controller therefore uses explicit values:

```yaml
region: us-east-1
vpcId: vpc-xxxxxxxxxxxxxxxxx
```

Get the current value with:

```bash
terraform -chdir=infra/terraform/aws/environments/dev output -raw vpc_id
```

The VPC ID is environment-specific but not secret.
