# Environment Model

## Overview

| Environment | Platform | Purpose |
|---|---|---|
| `local` | kind | GitOps and progressive-delivery development |
| `aws-dev` | Amazon EKS | Cloud infrastructure and delivery validation |

## Local

Location: `clusters/local/`

Components:

```text
kind
Argo CD
Argo Rollouts
ingress-nginx
Prometheus
demo-api
```

The local environment demonstrates canary routing, AnalysisRun, promotion, abort, rollback, and capacity guardrails.

## AWS Dev

Locations:

```text
clusters/aws-dev/
infra/terraform/aws/environments/dev/
```

Components:

```text
AWS VPC
Amazon EKS
Managed Node Group
EKS managed add-ons
Argo CD
AWS Load Balancer Controller
Karpenter AWS foundation
Karpenter CRDs and controller
Karpenter application EC2NodeClass
Karpenter On-Demand application NodePool
Karpenter Spot application NodePool
AWS FIS Spot interruption foundation
Karpenter FIS-only EC2NodeClass and Spot NodePool
CloudNativePG operator and CRDs
Single-instance PostgreSQL 17.10 Cluster
Encrypted 20Gi gp3 EBS persistence
demo-api
Application Load Balancer
```

The v0.5.0 Karpenter foundation includes IAM, node authorization, interruption
handling, and discovery tags. v0.5.1 adds the GitOps-managed CRDs and controller
on the stable system Managed Node Group. v0.5.2 adds an `EC2NodeClass` that
validates AWS launch configuration and discovery. v0.5.3 adds a bounded
On-Demand `NodePool` for explicitly opted-in application workloads. The normal
validation path keeps the NodePool idle; the separate scale test creates and
then removes temporary capacity. v0.5.4 adds a separately tainted Spot
`NodePool`, validates its EC2 purchase option, and checks the controller-to-SQS
interruption path. v0.5.5 adds a tag-isolated FIS-only Spot pool and an AWS FIS
experiment that can issue a real interruption notice to exactly one temporary
test node. v0.6.0 adds the cluster-wide CloudNativePG operator, admission
webhooks, and CRDs through Argo CD. Its two replicas run on separate stable
system nodes. v0.6.1 adds one PostgreSQL 17.10 instance on a stable system node
and one encrypted 20Gi gp3 EBS data volume. This first persistence baseline is
not highly available and has no backup or restore workflow.

## Deliberate Differences

| Concern | local | aws-dev |
|---|---|---|
| Kubernetes | kind | EKS |
| Ingress | ingress-nginx | AWS Load Balancer Controller |
| Workload | Rollout | Deployment |
| Progressive delivery | Enabled | Deferred |
| Exposure | Local hostname | ALB DNS |
| IAM | N/A | IAM and IRSA |
| Node capacity | kind nodes | system Managed Node Group plus isolated On-Demand, Spot, and FIS-only Karpenter application capacity |
| Database | N/A | single PostgreSQL instance with encrypted gp3 persistence |

The environments share GitOps principles but are not required to use identical traffic-routing implementations.
