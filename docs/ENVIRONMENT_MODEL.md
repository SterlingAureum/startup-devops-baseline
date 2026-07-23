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
demo-api
Application Load Balancer
```

The v0.5.0 Karpenter foundation includes IAM, node authorization, interruption
handling, and discovery tags. v0.5.1 adds the GitOps-managed CRDs and controller
on the stable system Managed Node Group. Dynamic nodes are not created until an
`EC2NodeClass` and `NodePool` are introduced.

## Deliberate Differences

| Concern | local | aws-dev |
|---|---|---|
| Kubernetes | kind | EKS |
| Ingress | ingress-nginx | AWS Load Balancer Controller |
| Workload | Rollout | Deployment |
| Progressive delivery | Enabled | Deferred |
| Exposure | Local hostname | ALB DNS |
| IAM | N/A | IAM and IRSA |
| Node capacity | kind nodes | system Managed Node Group; Karpenter provisioning deferred |

The environments share GitOps principles but are not required to use identical traffic-routing implementations.
