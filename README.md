# startup-devops-baseline

A local-first DevOps, GitOps, progressive delivery, and AWS EKS infrastructure baseline for early-stage teams.

This repository demonstrates a practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, Argo Rollouts, GHCR image publishing, Prometheus, and a small demo API service.

The repository now contains the completed local progressive-delivery and AWS
EKS baselines, isolated On-Demand and Spot application NodePools, a tag-scoped
AWS FIS drill, and a GitOps-managed CloudNativePG PostgreSQL persistence,
high-availability, S3 backup, point-in-time recovery, application integration,
and primary-failover baseline. Reusable CI quality gates protect both
pull-request validation and GHCR image publishing. Published application
images now carry a SHA tag, immutable OCI digest, structured source identity,
and GitHub build-provenance attestation. Successful main-branch builds now
turn that identity into a reviewable aws-dev GitOps promotion pull request.
The same immutable identity can then move only through the ordered
`aws-dev -> aws-test -> aws-prod` chain, with one target-scoped, reviewable PR
per transition and no direct cluster access from GitHub Actions. Cross-
environment movement now requires a fresh, reviewed source-release evidence
record, a separately reviewed source-runtime evidence record, target GitHub
Environment approval, and CODEOWNERS review. AWS test and production desired
state now use Argo Rollouts with ALB weighted target groups, canary-local Web
AnalysisRuns, and explicit manual progression. The same
governance boundary applies to environment-scoped rollback PRs.
Promoted values and live workloads now retain enough delivery metadata to
correlate source, build, Git promotion, Argo CD reconciliation, Pod image ID,
and the application-reported version. A manual rollback workflow can now
restore a previously reviewed, metadata-aware desired state through another
values-only pull request. The AWS environment now also enforces namespace and
admission guardrails plus default-deny NetworkPolicy isolation for application
and CloudNativePG data workloads, with explicit runtime-validated traffic
paths. AWS Secrets Manager, exact-secret IRSA, a namespaced External Secrets
Operator deployment, and an active ExternalSecret now provide the demo-api
PostgreSQL credential without committing the value to Git or Terraform state.
The v0.9 lifecycle now also defines a clean-room aws-dev/aws-test acceptance
sequence, guarded ephemeral test creation, reviewed canary completion,
CloudNativePG recovery validation, dependency-aware test destruction, exact
AWS residual-cost checks, and tamper-evident final closure evidence. The
repository remains intentionally smaller than a full production platform.
The v0.8 finalization added the `demo.dev.aureumstack.com` Route 53 endpoint,
ACM-backed HTTPS, HTTP redirection, a runtime-only EKS management `/32`, and
bounded security logging. v0.9 turns this single live AWS baseline into a
cost-aware, multi-environment GitOps promotion model without requiring three
permanently running portfolio clusters. v0.9.7 separates disposable
control-plane logging cost from formal production-parity validation and makes
the cleanup audit aware of terminal Karpenter Instant Fleet history. v0.9.8
provides one canonical, command-by-command operator Runbook for GitHub setup,
evidence collection, ordered Promotion, safe pause/resume, and cost cleanup.
v0.10.0 now defines the deterministic, environment-independent release
identity, derived phase/status model, resumable transition graph, and separated
GitHub-hosted, trusted-runtime, and human approval boundaries that the later
delivery automation increments must implement. This checkpoint is deliberately
offline: it adds no release orchestrator and grants no Workflow AWS/EKS access.
v0.10.1 upgrades the existing image, static qualification, ordered Promotion,
and rollback workflows into reusable delivery stages with typed inputs,
machine-readable outputs, an offline stage contract, and unchanged manual
entrypoints. The reusable stages remain GitHub-hosted, PR-oriented, and unable
to access AWS or EKS; runtime qualification remains reserved for the later
trusted executor.
v0.10.2 adds the event-driven, read-only release orchestrator. Protected-main
source, release, and evidence events plus manual `start`, `status`, and `resume`
now produce a deterministic snapshot and next-action decision, discover and
reuse matching open PRs, reject ambiguous duplicates, and block safely if
`main` changes during derivation. This checkpoint remains plan-only: it grants
no write, AWS, or EKS permission and does not dispatch a reusable stage.
v0.10.3 implements the separately trusted runtime qualification boundary for
`aws-dev` and `aws-test`: protected-main preflight, environment-labeled
ephemeral self-hosted execution, short-lived GitHub OIDC, exact-cluster IAM,
namespaced read-only EKS RBAC, release-bound live checks, and a secret-free
temporary result artifact. It is not yet dispatched by the orchestrator and
does not implement production runtime access.

## Current Version

```text
v0.10.3-trusted-runtime-qualification-executor
```
The completed v0.8 AWS EKS environment exposes demo-api through
`https://demo.dev.aureumstack.com` with the production-security baseline in
place. v0.9.0 converges every active aws-dev repository Application on `main`
and establishes the formal `aws-dev -> aws-test -> aws-prod` design contract.
Each AWS environment maps to its own EKS cluster and isolated stateful
resources. v0.9.1 separates
stable Helm environment configuration from promotable release identity for
aws-dev, aws-test, and aws-prod. v0.9.2 adds independent Terraform roots and
states plus a shared Kustomize base with dev/test/prod overlays. All three
declarations are statically validated. v0.9.3 adds main-sourced, stale-state
protected environment Promotion PRs that retain the exact image digest and
source commit while changing only the target release file. v0.9.4 requires a
reviewed, unexpired evidence record that matches the current source release,
adds CODEOWNERS and target-environment approvals, and generalizes rollback to
aws-dev, aws-test, and aws-prod. v0.9.5 adds test/prod ALB canary declarations,
Argo Rollouts, release-bound AnalysisRuns, local collection of reviewed AWS
runtime evidence, and a dual static/runtime Promotion gate. v0.9.6 adds the
guarded clean-room aws-test lifecycle, recovery drill sequence, cost-residual
audit, and final evidence contract. The live sequence completed aws-dev and
aws-test validation plus the governed aws-test to aws-prod Promotion, while
aws-prod remained statically validated by design. v0.9.7 defaults disposable
dev/test control-plane ingestion off, provides an explicit all-five-log
production-parity checkpoint, preserves the live profile during management-IP
updates, and ignores only terminal or expired Instant Fleet history after
exact cost-resource checks pass. v0.9.8 closes the manual-operability
documentation gap with a single release procedure that distinguishes GitHub
workflow run IDs from UTC runtime-evidence IDs, corrects the Promotion input
name, and documents how a destroyed aws-test cluster can remain a valid source
for time-bounded static production Promotion.
v0.10.0 converts that validated manual procedure into a machine-readable
application contract and release-state schema. It fixes the only successful
phase path, treats absent environments and unavailable runtime executors as
resumable waits, preserves manual production approval and merge, and includes
offline negative tests for unsafe policy mutations. Workflow implementation,
OIDC/IAM/RBAC, and live runtime orchestration remain later v0.10 increments.
v0.10.1 adds `workflow_call` interfaces to the four existing delivery
workflows, publishes stable stage outputs, and records their script primitives,
mutation scopes, allowed environments, and security boundary in
`delivery/contracts/demo-api-stages.json`. It preserves all v0.9 dispatch and
push paths and does not introduce an orchestrator, automatic merge, or cluster
access.
v0.10.2 introduces `.github/workflows/demo-api-release-orchestrator.yaml`, a
read-only fact collector, and a deterministic planner. The orchestrator derives
one state and recommendation from current release files, matching evidence,
open PR contents, environment availability, and protected-main freshness. Its
workflow artifacts are diagnostic observations rather than mutable release
state. Actual stage dispatch remains deferred to v0.10.4 through v0.10.6, after
the v0.10.3 trusted runtime boundary exists.
v0.10.3 adds `.github/workflows/demo-api-runtime-qualification.yaml`, the
runtime executor/result contracts, a short-lived OIDC IAM and EKS access-entry
module for dev/test, GitOps-managed read-only Roles, and deterministic runtime
collection. An unavailable runner or absent disposable environment remains a
safe wait; no GitHub-hosted fallback or automatic Terraform apply is allowed.
The temporary runtime result becomes unified qualification evidence in
v0.10.4.

## Platform Architecture

```text
                         GitHub Repository

                                  |
                                  v

                               Argo CD

                         GitOps Control Plane

                                  |
                                  v

                      Kubernetes Applications

                                  |
                                  v

                         Application Delivery

                    - Helm
                    - Argo Rollouts


                                  |
                                  v

                          demo-api Workload



                 +----------------+----------------+

                 |                                 |

                 v                                 v


        Local Kubernetes Environment       AWS Kubernetes Environment


                 kind                         Amazon EKS


                  |                               |


          ingress-nginx              AWS Load Balancer
                                     Controller


                  |                               |


          Local Ingress                     AWS ALB
```

Both environments use Git and Argo CD as the desired-state control plane.
The local environment focuses on progressive delivery, while the AWS
environment covers cloud infrastructure, AWS-native application delivery,
dynamic capacity, and the CloudNativePG database control plane.
The diagram shows the aws-dev Deployment path. aws-test and aws-prod replace
the single workload/Service hop with an Argo Rollout, stable/canary Services,
ALB weighted target groups, and a release-bound AnalysisRun.

## Deployment Options

### Local GitOps Environment

Use the local environment for fast iteration, GitOps validation, and
progressive-delivery experiments.

See `docs/LOCAL_DEPLOYMENT.md`.

### AWS EKS Environment

Use the AWS environment for Terraform-managed infrastructure, Amazon EKS,
Argo CD bootstrap, AWS-native ingress, and cloud validation.

See `docs/AWS_EKS_DEPLOYMENT.md`.

## Repository Structure

```text
startup-devops-baseline/
├── .github/
│   └── workflows/
├── apps/
│   └── demo-api/
├── clusters/
│   ├── local/
│   └── aws/
│       ├── base/
│       └── overlays/{dev,test,prod}/
├── infra/
│   └── terraform/aws/
│       ├── modules/
│       └── environments/{dev,test,prod}/
├── docs/
├── delivery/
│   └── contracts/
├── evidence/
│   └── demo-api/
├── examples/
├── platform/
└── scripts/
```

## Documentation

### Architecture

- `docs/ARCHITECTURE.md`
- `docs/AWS_EKS_ARCHITECTURE.md`
- `docs/ENVIRONMENT_MODEL.md`
- `docs/MULTI_ENVIRONMENT_GITOPS_MODEL.md`

### Deployment and Operations

- `docs/MULTI_ENVIRONMENT_RELEASE_RUNBOOK.md`
- `docs/LOCAL_DEPLOYMENT.md`
- `docs/AWS_EKS_DEPLOYMENT.md`
- `docs/AWS_EKS_DESTROY_RUNBOOK.md`
- `docs/AWS_PROGRESSIVE_DELIVERY.md`
- `docs/TROUBLESHOOTING.md`

### GitOps and Delivery

- `docs/RELEASE_ORCHESTRATION_MODEL.md`
- `docs/REUSABLE_DELIVERY_STAGES.md`
- `docs/RELEASE_ORCHESTRATOR.md`
- `docs/CI_IMAGE_WORKFLOW.md`
- `docs/DELIVERY_TRACEABILITY.md`
- `docs/GITOPS_ROLLBACK.md`
- `docs/GITOPS_WORKFLOW.md`
- `docs/PROMOTION_GOVERNANCE.md`
- `docs/V0.7_FINAL_VALIDATION.md`
- `docs/GHCR_IMAGE_WORKFLOW.md`
- `docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md`

### Terraform

- `docs/TERRAFORM_OUTPUTS.md`
- `docs/TERRAFORM_STATE_MANAGEMENT.md`

### Project Evolution

- `CHANGELOG.md`
- `docs/ROADMAP.md`
