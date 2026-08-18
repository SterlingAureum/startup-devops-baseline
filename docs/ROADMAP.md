# Roadmap

This roadmap describes the intended evolution of the repository. It is
not a fixed delivery schedule.

## v0.1 - Local GitOps Baseline

Status: Completed

Delivered:

- kind local Kubernetes cluster
- Argo CD GitOps control plane
- app-of-apps root Application
- demo-api workload
- Helm-based deployment
- ingress-nginx managed by Argo CD
- local ingress access
- lightweight Prometheus monitoring

## v0.2 - CI and Image Validation Baseline

Status: Completed

Delivered:

- GitHub Actions validation
- Docker image build checks
- Helm lint and template validation
- GHCR image publishing foundation

## v0.3 - Progressive Delivery Baseline

Status: Completed

Delivered across v0.3.0 through v0.3.5:

- Argo Rollouts
- ingress-nginx canary routing
- stable and canary Services
- GHCR image publishing
- manual GitOps image promotion
- Prometheus AnalysisTemplate and AnalysisRun
- rollback procedures
- rollout capacity guardrails

## v0.4 - AWS EKS Infrastructure Baseline

Status: Completed

Delivered across v0.4.0 through v0.4.4:

- Terraform environment and reusable module structure
- GitHub Actions based Terraform validation
- Multi-AZ VPC with public and private subnets
- Internet Gateway and development NAT Gateway
- Amazon EKS control plane
- On-Demand Managed Node Group in private subnets
- EKS managed add-ons
- OIDC, IAM, and workload-specific IRSA roles
- Argo CD bootstrap on Amazon EKS
- AWS Load Balancer Controller with IRSA
- aws-dev App of Apps
- demo-api Deployment exposed through an internet-facing ALB
- unified infrastructure and application validation
- dependency-aware AWS environment teardown workflow
- AWS architecture, Terraform state, and troubleshooting documentation
- explicit VPC configuration for the AWS Load Balancer Controller

## v0.5 - Karpenter Autoscaling Baseline

Status: Completed

Goal:

Introduce dynamic node provisioning and workload-aware capacity
management.

Planned scope:

- AWS IAM, interruption handling, and discovery foundation - delivered in v0.5.0
- Karpenter CRD and controller installation - delivered in v0.5.1
- controller IRSA and stable system-node placement - delivered in v0.5.1
- application EC2NodeClass and AWS resource discovery - delivered in v0.5.2
- On-Demand application NodePool design - delivered in v0.5.3
- system and application workload separation - delivered in v0.5.3
- scheduling constraints and bounded capacity - delivered in v0.5.3
- controlled scale-out and consolidation-driven scale-in - delivered in v0.5.3
- isolated Spot application capacity and scale validation - delivered in v0.5.4
- controller, SQS, and EventBridge interruption readiness - delivered in v0.5.4
- tag-isolated AWS FIS foundation and dedicated test capacity - delivered in v0.5.5
- controlled AWS FIS interruption and replacement drill - delivered and runtime-validated in v0.5.5

## v0.6 - CloudNativePG Data Platform

Status: Completed

Goal:

Introduce Kubernetes-native database operations.

Incremental scope:

- v0.6.0 - CloudNativePG operator, CRDs, webhooks, GitOps lifecycle, and stable
  system-node placement - delivered
- v0.6.1 - gp3 persistence baseline and a single PostgreSQL instance -
  delivered
- v0.6.2 - dedicated On-Demand database capacity and a three-instance,
  cross-AZ high-availability cluster - delivered
- v0.6.3 - S3 backup and WAL archiving through the Barman Cloud CNPG-I
  plugin - delivered
- v0.6.4 - isolated latest-state restore, point-in-time recovery, data
  integrity, and recovery-resource cleanup validation - delivered
- v0.6.5 - demo-api application credentials, RW Service integration,
  primary-Pod failover, application reconnection, and version finalization -
  delivered

## v0.7 - CI/CD and GitOps Promotion Baseline

Status: Completed

Goal:

Close the delivery loop from validated source changes to immutable images,
reviewable GitOps promotion, Argo CD reconciliation, and runtime identity
verification.

Incremental scope:

- v0.7.0 - reusable CI quality gates, isolated demo-api unit tests, Helm
  rendering, shell syntax validation, and publish-job dependency - delivered
- v0.7.1 - immutable image digest, build provenance, and artifact identity -
  delivered
- v0.7.2 - automated, reviewable aws-dev GitOps promotion pull request -
  delivered
- v0.7.3 - desired-state, Argo CD revision, Pod image ID, and application
  version traceability - delivered
- v0.7.4 - Git-based image rollback and end-to-end delivery validation -
  delivered

## v0.8 - Production Security Baseline

Status: Completed

Goal:

Add production-oriented secret, network, workload, and admission controls.

Incremental scope:

- v0.8.0 - workload runtime hardening, secret and configuration scanning,
  pre-publication image vulnerability gates, immutable GitHub Action pins,
  SPDX SBOM generation, and digest-bound attestations - delivered
- v0.8.1 - Namespace, Pod Security Admission, ResourceQuota, LimitRange, and
  native admission-policy guardrails - delivered
- v0.8.2 - EKS NetworkPolicy enablement and application/data-platform network
  isolation - delivered
- v0.8.3 - External Secrets Operator, exact-secret IRSA, namespaced AWS
  SecretStore foundation, and NetworkPolicy rebuild portability - delivered
- v0.8.4 - PostgreSQL credential migration into AWS Secrets Manager and
  ExternalSecret cutover - delivered
- v0.8.5 - PostgreSQL application credential rotation and workload reload
  validation - delivered; candidate staging, guarded cutover, automatic
  compensation, guarded AWSPREVIOUS rollback and forward-recovery implementation,
  live round trip, and final-state validation completed
- v0.8.6 - Route 53 DNS, ACM/ALB HTTPS, EKS endpoint and control-plane logging
  hardening, dynamic management-IP privacy, and final security validation -
  delivered and live AWS validation completed

## v0.9 - Multi-Environment GitOps Promotion Baseline

Status: Completed

Goal:

Promote one immutable application artifact through isolated AWS development,
test, and production environments with reviewable GitOps controls.

Incremental scope:

- v0.9.0 - v0.8 main convergence, environment topology, promotion boundaries,
  isolation rules, lifecycle model, and active GitOps revision validation -
  delivered
- v0.9.1 - Helm environment configuration and release identity separation,
  ordered multi-values rendering, release-only aws-dev promotion/rollback, and
  three-environment static Helm validation - delivered
- v0.9.2 - reusable AWS base, dev/test/prod Terraform and GitOps declarations,
  non-overlapping address plans, independent state roots, and production
  safety constraints - delivered
- v0.9.3 - ordered build-once environment promotion, main-sourced release
  capture, immutable GHCR identity verification, target concurrency,
  stale-state protection, and release-only Promotion PRs - delivered
- v0.9.4 - reviewed static release evidence, target GitHub Environment
  approvals, CODEOWNERS, and environment-scoped rollback governance - delivered
- v0.9.5 - AWS test/prod progressive delivery with ALB, Argo Rollouts,
  release-bound AnalysisRuns, and reviewed runtime evidence - delivered
- v0.9.6 - clean-room dev/test sequence, production static validation, guarded
  recovery/teardown, cost-residual audit, and final evidence - delivered and
  live acceptance completed
- v0.9.7 - cost-aware EKS control-plane logging profiles, bounded retention,
  endpoint-update profile preservation, and terminal EC2 Fleet audit handling
  - delivered
- v0.9.8 - canonical manual multi-environment release Runbook, one-time GitHub
  governance setup, exact evidence and Promotion commands, ID disambiguation,
  safe pause/resume, troubleshooting, and cleanup checklist - delivered;
  v0.9 version line closed

## v0.10 - Release Orchestration and Delivery Automation

Status: Completed

Goal:

Turn the existing build, GitOps release, runtime evidence, qualification, and
ordered promotion controls into one resumable delivery workflow while
retaining human production approval.

Incremental scope:

- v0.10.0 - deterministic release identity, machine-readable application
  contract and release-state schema, derived phase/status model, execution and
  production safety boundaries, resumable transition contract, and offline
  positive/negative validation - delivered
- v0.10.1 - reusable image, static qualification, Promotion, evidence, and
  rollback stages with typed workflow-call interfaces, stable outputs,
  CI-provider-neutral script primitives, and offline boundary validation -
  delivered
- v0.10.2 - event-driven start, status, and resume orchestration with
  read-only Git/GitHub fact snapshots, idempotent open-PR discovery,
  deterministic next-action planning, concurrency, stale-main handling, and
  offline positive/negative behavior validation - delivered
- v0.10.3 - protected-main trusted runtime qualification, ephemeral
  self-hosted execution, AWS OIDC, environment-isolated IAM and Kubernetes
  RBAC, immutable runtime artifacts, and safe absent/unavailable handling -
  delivered
- v0.10.3.1 - Terraform formatting and load-restriction-safe dev/test runtime
  RBAC Application assembly, with prod exclusion and render regressions -
  delivered
- v0.10.3.2 - storage-bounded trusted-runtime mutation fixtures that exclude
  local Terraform caches, state, plans, and real variable files while
  retaining dependency locks and tracked configuration - delivered
- v0.10.4 - repository-variable-gated post-release aws-dev static
  qualification, passive GitOps convergence, trusted runtime validation,
  deterministic deployment-scope hashing, and reviewed unified Qualification
  Bundle evidence - delivered
- v0.10.5 - automatic aws-dev to aws-test Promotion preparation, reviewed
  Canary progression, AnalysisRun verification, test scope hashing, and
  reviewed aws-test Qualification Bundle evidence - delivered
- v0.10.6 - automatic production Promotion preparation with retained aws-prod
  Environment approval and reviewed release-only PR merge - delivered
- v0.10.7 - strictly read-only status, exact failed-Attempt retry, secret-free
  attempt diagnostics, source-ancestry supersede handling, explicit Bundle
  expiry/drift states, and governed dev/test rollback handoff - delivered
- v0.10.8 - clean-room dev/test/prod-static acceptance contract,
  interrupted-run and environment-restoration procedure, deterministic
  expiry/retry/rollback-handoff checks, cost cleanup, tamper-evident closure
  evidence, and final command-by-command Runbook - delivered; live acceptance
  is recorded only after the evidence-only PR merges

The application release path does not automatically create EKS environments.
An absent disposable environment is a resumable wait, and production approval
and PR merge remain human controls throughout v0.10.

## v0.11 - Observability and Production Readiness Baseline

Status: Planned

Goal:

Make the multi-environment baseline observable and operationally sustainable.

Planned scope:

- Prometheus production deployment
- Grafana dashboards
- Alertmanager and actionable alert routing
- centralized logging
- application SLI/SLO metrics
- platform health monitoring
- remote Terraform state bootstrap and locking
- platform upgrade and dependency lifecycle
- clean-room infrastructure and GitOps rebuild
- recovery objectives and operational readiness review
- end-to-end security, observability, delivery, and cost validation

## v1.0 - AI Infrastructure Extension

Status: Planned

Goal:

Extend the platform toward AI workloads.

Planned scope:

- GPU node pool
- NVIDIA device plugin
- GPU scheduling and isolation
- GPU monitoring
- vLLM inference service
- OpenAI-compatible API serving
- model storage workflow

## v1.1 - AIOps Operations Extension

Status: Planned

Goal:

Introduce AI-assisted platform operations.

Planned scope:

- alert summarization
- incident triage
- GitOps diagnosis
- rollout failure analysis
- runbook automation
- human-approved remediation workflows
- AIOps safety boundaries
