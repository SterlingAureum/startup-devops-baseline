# AWS EKS Architecture

## Purpose

This document describes the runtime architecture of the AWS EKS environment.

## Architecture

### GitOps Management Architecture

```text
                         GitHub Repository

                                |
                                v

                             Argo CD

                                |
                                v

                    aws-dev-root Application

                                |
       +-------------+-------------+-------------+-------------+
       |             |             |             |
       v             v             v             v

      AWS LBC    Karpenter CRDs   Karpenter      demo-api

    Application     Application    Application   Application

       |             |             |             |
       v             v             v             v

 Controller Pods    CRDs      Controller Pods  demo-api Pods

 AWS LBC `vpcId` is rendered by bootstrap and preserved by the root Application.

 Karpenter controller
          |
          v
 application EC2NodeClass
          |
          v
 application-ondemand NodePool
          |
          v
 NodeClaim and temporary On-Demand application node

```

### Runtime Traffic Flow

```text
                         Users

                           |
                           v

                  AWS Application Load Balancer

                           |
                           v

                 Kubernetes Ingress

                           |
                           v

                 Kubernetes Service

                           |
                           v

                    demo-api Pods




               AWS Load Balancer Controller Pods

                           |
                           |
                           | watches
                           v

                 Kubernetes Ingress

                           |
                           |
                           v

                        AWS API

                           |
                           |
                           v

               ALB lifecycle management


Notes: AWS Load Balancer Controller watches Ingress resources and manages ALB lifecycle.

```

### Infrastructure

```text
Terraform

    |
    v

AWS VPC

    |
    v

Amazon EKS

    |
    v

On-Demand System Managed Node Group

    |
    v

Platform Controllers


Terraform also prepares

Karpenter IAM + EKS Access Entry
SQS Interruption Queue + EventBridge
Subnet + Security Group Discovery Tags
```

Infrastructure ownership:

```text
Terraform
├── VPC and subnets
├── Internet Gateway and NAT Gateway
├── Amazon EKS
├── EKS managed add-ons
├── stable system Managed Node Group
├── Karpenter IAM roles and policies
├── Karpenter node EKS access entry
├── SQS interruption queue and EventBridge rules
├── Karpenter discovery tags
├── IAM roles and policies
└── OIDC provider

Bootstrap scripts
├── kubeconfig
├── Argo CD installation
├── IRSA ServiceAccount annotation
└── environment-specific ALB Application rendering

Argo CD
├── AWS Load Balancer Controller
├── Karpenter CRDs
├── Karpenter controller
├── Karpenter application EC2NodeClass
├── Karpenter On-Demand application NodePool
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
Karpenter controller → IRSA role
Karpenter node → dedicated EC2 node role and EKS access entry
```

The Karpenter controller is constrained to the stable Managed Node Group
labeled `workload=system`. The application EC2NodeClass supplies IAM
instance-profile, private-subnet, security-group, and AMI discovery.
`application-ondemand` provisions only On-Demand Linux/amd64 nodes for pods
that select `workload=application` and tolerate
`dedicated=application:NoSchedule`. CPU, memory, and node-count limits bound the
development environment, while consolidation removes empty capacity.

## IMDS and VPC Discovery

Nodes use IMDSv2 with hop limit `1`. The AWS Load Balancer Controller therefore uses explicit values:

```yaml
region: us-east-1
vpcId: vpc-xxxxxxxxxxxxxxxxx
```

The repository stores `__VPC_ID__`, not a real VPC identifier. During
bootstrap, the script gets the current value with:

```bash
terraform -chdir=infra/terraform/aws/environments/dev output -raw vpc_id
```

It renders the value into a temporary copy of the Application and applies that
copy to Argo CD. The VPC ID is environment-specific but not secret; keeping it
out of Git prevents stale environment coupling.
