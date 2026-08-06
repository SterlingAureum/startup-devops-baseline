# Environment Model

## Overview

The repository distinguishes the local development sandbox from the formal AWS
promotion chain. Each named AWS environment represents an independent EKS
cluster and an independent operational boundary.

| Environment | Platform | Role | Promotion chain | v0.9 runtime expectation |
|---|---|---|---|---|
| `local` | kind | Local GitOps and progressive-delivery sandbox | No | Retained |
| `aws-dev` | Amazon EKS | First cloud integration environment | Yes | Required and live-validated |
| `aws-test` | Amazon EKS | Isolated pre-production environment | Yes | Created and live-validated at least once |
| `aws-prod` | Amazon EKS | Production desired state and governance target | Yes | Complete declarations required; live creation optional in v0.9 |

The target AWS topology is therefore three environments and three clusters:

| Environment | Cluster identity | Intended lifecycle |
|---|---|---|
| `aws-dev` | `startup-devops-baseline-dev` | Disposable and rebuildable |
| `aws-test` | `startup-devops-baseline-test` | Ephemeral; created for validation and then destroyed |
| `aws-prod` | `startup-devops-baseline-prod` | Persistent production boundary |

Only `aws-dev` is required to exist at the v0.9.5 checkpoint. Git now contains
complete Terraform and GitOps declarations for all three environments;
aws-test and aws-prod remain unapplied until their later validation stages.

## Local Sandbox

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

The local environment supports fast chart iteration, canary routing,
AnalysisRun, promotion, abort, rollback, and capacity experiments. It can use
development image identities and `HEAD` while it is outside the formal AWS
promotion chain.

## AWS Dev Baseline

Locations:

```text
clusters/aws/base/
clusters/aws/overlays/dev/
infra/terraform/aws/environments/dev/
```

The existing aws-dev cluster contains the AWS infrastructure, Argo CD,
application delivery, Karpenter capacity, CloudNativePG data platform,
External Secrets integration, security controls, HTTPS ingress, and validated
backup, recovery, failover, credential-rotation, and network-policy paths built
through v0.4-v0.8.

At v0.9.5, the root Application and every internal-repository child
Application track `main`. Third-party sources remain pinned to their reviewed
Chart or component versions.

The active demo-api Application loads:

```text
values/environments/aws-dev.yaml
values/releases/aws-dev.yaml
```

The environment file owns runtime configuration and the release file owns the
immutable artifact identity. aws-test and aws-prod have the same split for
static Helm validation without claiming that either cluster currently exists.

The build workflow writes only the aws-dev release through a reviewable PR.
The ordered environment workflow then permits only aws-dev to aws-test and
aws-test to aws-prod. Every transition reads the source release from `main`,
retains its complete image and build identity, verifies the digest-addressed
GHCR artifact, and changes only the target release file. A target-scoped
concurrency group serializes competing attempts, and any main movement during
PR preparation invalidates the captured source state.

Before a cross-environment PR can be created, a separate source qualification
workflow must record passing, reviewed evidence on `main`. The record is bound
to the current source release SHA-256 and expires after seven days by default.
Promotion and rollback enter the target GitHub Environment boundary, while
CODEOWNERS and branch protection preserve the human merge decision. At this
v0.9.5 adds a separate runtime record collected from the restricted local
operations path. Cross-environment promotion requires both records on `main`,
fresh and bound to the current source release. The runtime record proves live
source identity and, for test/prod, completed ALB Rollout and AnalysisRun state;
it does not claim that an environment exists until the collector succeeds.

## Declared AWS Profiles

| Setting | dev | test | prod |
|---|---|---|---|
| VPC CIDR | `10.20.0.0/16` | `10.30.0.0/16` | `10.40.0.0/16` |
| Service CIDR | `172.20.0.0/16` | `172.21.0.0/16` | `172.22.0.0/16` |
| DNS | `demo.dev.aureumstack.com` | `demo.test.aureumstack.com` | `demo.prod.aureumstack.com` |
| Control-plane logs | 14 days | 30 days | 90 days minimum |
| NAT | Single | Single | One per AZ |
| Backup force destroy | Allowed | Allowed for ephemeral validation | Rejected |
| Secret recovery | Immediate | 7 days | 30 days required |

Terraform state is rooted independently beneath `environments/dev`,
`environments/test`, and `environments/prod`; ordinary CLI workspaces are not
used as the isolation boundary. Environment names are locked in each root so a
tfvars override cannot make one state claim another environment's names.

## Environment Isolation Boundary

Each AWS environment owns its own:

- EKS cluster and Argo CD installation;
- VPC, address ranges, security groups, and load balancers;
- Terraform state and environment credentials;
- Secrets Manager Secrets, IAM roles, and IRSA bindings;
- CloudNativePG cluster, data volumes, and backup destination;
- Route 53 application hostname and ACM certificate;
- environment configuration, release record, and validation evidence.

Application images are shared by immutable registry digest. Secret values,
database contents, backup objects, certificates, and Terraform state never move
through the application promotion chain.

## AWS Account Boundary

The portfolio validation path may create aws-dev and aws-test sequentially in
one AWS account to limit cost. Unique names, CIDRs, state, IAM resources, and
data resources still preserve environment isolation within that account.

This is not presented as the final production account model. A production
deployment should place aws-prod in a separately governed AWS account; teams
with stronger separation requirements should also place dev and test in
dedicated accounts.

## Lifecycle and Cost Model

The repository does not require three EKS clusters to run continuously:

1. Keep or rebuild aws-dev and validate the candidate release.
2. Create aws-test, promote the same digest, run pre-production and failure
   tests, then destroy the environment after collecting non-sensitive evidence.
3. Render and statically validate aws-prod declarations in v0.9; a live
   production deployment is optional.

This sequential model proves independent lifecycles without turning the
portfolio environment into three permanent sources of AWS cost.

## Deliberate Differences

| Concern | local | aws-dev | aws-test | aws-prod |
|---|---|---|---|---|
| Kubernetes | kind | EKS | EKS | EKS |
| Cluster | Local sandbox | Independent dev | Independent test | Independent prod |
| Ingress | ingress-nginx | AWS ALB | AWS ALB | AWS ALB |
| Release entry | Direct development | Build output | From aws-dev | From aws-test |
| Progressive delivery | Enabled | Existing Deployment path | ALB Canary declared | ALB Canary plus approval declared |
| State and data | Disposable | Isolated dev | Isolated test | Isolated prod |
| Lifetime | Developer-controlled | Rebuildable | Ephemeral | Persistent |

Environment-specific capacity, retention, rollout, and availability settings
may differ. The immutable application digest and its source/build identity must
not change during aws-dev to aws-test to aws-prod promotion.

See `docs/MULTI_ENVIRONMENT_GITOPS_MODEL.md` for the promotion and repository
design contract.
