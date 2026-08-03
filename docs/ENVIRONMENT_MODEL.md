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
Karpenter database EC2NodeClass and On-Demand NodePool
Karpenter isolated On-Demand database recovery NodePool
CloudNativePG operator and CRDs
Three-instance PostgreSQL 17.10 HA Cluster
Three encrypted 20Gi gp3 EBS data volumes
S3 physical backups, WAL archiving, and PITR validation
demo-api with PostgreSQL readiness and failover validation
Application Load Balancer
Route 53 public hostname and Alias
ACM certificate and HTTPS redirect
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
and one encrypted 20Gi gp3 EBS data volume. v0.6.2 moves PostgreSQL onto a
dedicated Karpenter On-Demand NodePool and expands it to one primary and two
replicas. Required hostname anti-affinity gives each instance a different node,
while topology spreading balances them `2+1` across the two development
Availability Zones. One synchronous standby acknowledgement is required. The
v0.6.3 Barman Cloud plugin archives WAL files continuously and creates daily
physical base backups in a versioned, encrypted S3 bucket through a dedicated
IRSA role. v0.6.4 uses a one-node isolated recovery pool to validate both
latest-state restore and timestamp-based PITR in independent clusters, then
removes their temporary PVC, EBS, NodeClaim, and EC2 resources without
changing the source cluster. v0.6.5 connects demo-api to the operator-managed
RW Service using the generated application identity, then validates primary-Pod
failover, RW Service movement, application reconnection, and committed-data
preservation.

## Deliberate Differences

| Concern | local | aws-dev |
|---|---|---|
| Kubernetes | kind | EKS |
| Ingress | ingress-nginx | AWS Load Balancer Controller |
| Workload | Rollout | Deployment |
| Progressive delivery | Enabled | Deferred |
| Exposure | Local hostname | Route 53 hostname with ACM-backed HTTPS |
| IAM | N/A | IAM and IRSA |
| Node capacity | kind nodes | system Managed Node Group plus isolated application and database Karpenter capacity |
| Database | Disabled | three PostgreSQL instances on dedicated On-Demand nodes with encrypted gp3 persistence, S3 physical backups, isolated PITR, and demo-api failover validation |

The environments share GitOps principles but are not required to use identical traffic-routing implementations.
