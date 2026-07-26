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

      AWS LBC       Karpenter       CloudNativePG      demo-api

    Application    Applications      Application      Application

       |             |                 |                 |
       v             v                 v                 v

 Controller Pods  CRDs + Controller  CRDs + Operator  demo-api Pods

                                       |
                                       v

                              PostgreSQL Application

                                       |
                                       v

                       HA Cluster + 3 PVCs + gp3 EBS

 AWS LBC `vpcId` is rendered by bootstrap and preserved by the root Application.

 Karpenter controller
          |
          v
 application EC2NodeClass
          |
          v
 application capacity tiers
    |                 |                 |
    v                 v                 v
 On-Demand         Spot NodePool   FIS-only Spot NodePool
 NodePool               |                 |
    |                    |                 v
    +--------------------+------> NodeClaims and temporary application nodes

 database EC2NodeClass
          |
          v
 database-ondemand NodePool
          |
          v
 3 persistent On-Demand nodes
          |
          v
 PostgreSQL primary + 2 replicas

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
AWS FIS Role + Spot Interruption Template
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
├── AWS FIS experiment role and template
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
├── CloudNativePG operator and CRDs
├── PostgreSQL Cluster and gp3 StorageClass
├── Karpenter application EC2NodeClass
├── Karpenter FIS-only EC2NodeClass
├── Karpenter database EC2NodeClass
├── Karpenter On-Demand application NodePool
├── Karpenter Spot application NodePool
├── Karpenter FIS-only Spot NodePool
├── Karpenter On-Demand database NodePool
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
AWS FIS → dedicated Spot interruption role
CloudNativePG cluster → dedicated S3 backup IRSA role
```

The Karpenter controller is constrained to the stable Managed Node Group
labeled `workload=system`. The application EC2NodeClass supplies IAM
instance-profile, private-subnet, security-group, and AMI discovery.
`application-ondemand` and `application-spot` provision Linux/amd64 capacity.
Their different `NoSchedule` taints make the pools mutually exclusive unless a
workload explicitly tolerates both. CPU, memory, and node-count limits bound
the development environment, while consolidation removes empty capacity.

The separate `database` EC2NodeClass and `database-ondemand` NodePool reuse the
existing Karpenter node IAM role and private-subnet discovery. A
`dedicated=database:NoSchedule` taint isolates database nodes from normal
applications. The pool allows three 2-vCPU On-Demand nodes and consolidates
only empty nodes, avoiding underutilization-driven replacement of active
database capacity.

CloudNativePG `1.30.0` is installed from the official Helm chart through an
Argo CD Application. Its two operator replicas use the same stable
`workload=system` Managed Node Group and required hostname anti-affinity. The
operator is cluster-wide so later v0.6 increments can manage database
namespaces.

v0.6.1 adds `postgresql-baseline`, a single PostgreSQL `17.10` instance in the
`data-platform` namespace. It temporarily uses the same stable system Managed
Node Group with Guaranteed 500m CPU and 1Gi memory. Its 20Gi data PVC is
dynamically provisioned from the `gp3-cnpg` StorageClass as an encrypted gp3
EBS volume. The existing EBS CSI controller IRSA role performs provisioning,
so this increment adds no IAM role or Terraform change.

v0.6.2 expands the same Cluster to one primary and two replicas. Required
hostname anti-affinity places the instances on three different EC2 nodes.
Required zone affinity matches the database NodePool's two eligible AZs, and
Kubernetes topology spreading balances the instances `2+1` with a maximum skew
of one. PostgreSQL requires one synchronous standby acknowledgement,
strengthening durability during a single instance failure.

The database Application self-heals but does not automatically prune, and the
Namespace, StorageClass, and Cluster each carry `Prune=false`. This protects
stateful resources from ordinary Git deletion. The explicit destroy workflow
remains destructive and deletes the Cluster, all three PVCs, and their EBS
volumes. v0.6.2 is highly available at the database-instance and node level but
does not protect against deletion or corruption of the EBS data set.

v0.6.3 adds cert-manager and the Barman Cloud `0.13.0` CNPG-I plugin in the
same `cnpg-system` namespace as the CloudNativePG operator. The plugin injects
a bounded sidecar into each PostgreSQL Pod. A Terraform-managed S3 bucket
blocks public access, requires TLS, enables versioning, and uses Amazon S3
managed encryption. The `postgresql-baseline` ServiceAccount assumes a
database-specific IRSA role; no static AWS access key is stored in Kubernetes
or Git.

The `ObjectStore` continuously archives WAL files and retains a seven-day
recovery window. Daily physical base backups prefer a standby to reduce I/O on
the primary. The environment-specific S3 bucket name is rendered only into the
live ObjectStore and protected by Argo CD `RespectIgnoreDifferences`; the rest
of the backup configuration remains GitOps-managed. Restore and PITR are not
claimed until v0.6.4 executes them against a separate recovery Cluster.

The Karpenter controller receives interruption events through the encrypted SQS
queue populated by EventBridge. For a Spot interruption warning, Karpenter can
taint and drain the affected node while requesting replacement capacity.

The FIS template targets `COUNT(1)` running Spot instance with the unique
`KarpenterFISTest` EC2 tag. Only the test-only EC2NodeClass propagates that tag,
so normal On-Demand and Spot application capacity remains outside the
experiment blast radius.

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
