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

Status: Planned

Goal:

Add production-oriented secret, network, workload, and admission controls.

Planned scope:

- external secret management
- AWS Secrets Manager integration
- application credential rotation
- TLS and DNS workflow
- NetworkPolicy
- Pod Security controls
- ResourceQuota and LimitRange
- admission policy validation

## v0.9 - Observability and SRE Baseline

Status: Planned

Goal:

Build a production observability foundation.

Planned scope:

- Prometheus production deployment
- Grafana dashboards
- Alertmanager
- centralized logging
- application SLI/SLO metrics
- platform health monitoring

## v1.0 - Production Readiness Baseline

Status: Planned

Goal:

Finalize the reusable DevOps and platform-engineering baseline.

Planned scope:

- production-like environment and promotion model
- remote Terraform state bootstrap and locking
- platform upgrade and dependency lifecycle
- clean-room infrastructure and GitOps rebuild
- recovery objectives and operational readiness review
- end-to-end security, observability, delivery, and cost validation

## v1.1 - AI Infrastructure Extension

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

## v1.2 - AIOps Operations Extension

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
