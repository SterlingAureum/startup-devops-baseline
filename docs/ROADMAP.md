# Roadmap

This roadmap describes the intended evolution of the repository. It is
not a fixed delivery schedule.

## v0.1 - Local GitOps Baseline

Status: Completed

Delivered: - kind local Kubernetes cluster - Argo CD GitOps control
plane - app-of-apps root Application - demo-api workload - Helm-based
deployment - ingress-nginx managed by Argo CD - local ingress access -
lightweight Prometheus monitoring

## v0.2 - CI and Image Validation Baseline

Status: Completed

Delivered: - GitHub Actions validation - Docker image build checks -
Helm lint and template validation - GHCR image publishing foundation

## v0.3 - Progressive Delivery Baseline

Status: Completed

Delivered across v0.3.0 through v0.3.5:

-   Argo Rollouts
-   ingress-nginx canary routing
-   stable and canary Services
-   GHCR image publishing
-   manual GitOps image promotion
-   Prometheus AnalysisTemplate and AnalysisRun
-   rollback procedures
-   rollout capacity guardrails

## v0.4 - AWS EKS Infrastructure Baseline

Status: Completed

### v0.4.0 Terraform and CI Skeleton

-   Terraform environment and module layout
-   AWS provider configuration
-   static validation workflow

### v0.4.1 VPC Network Baseline

-   Multi-AZ public and private subnets
-   Internet Gateway
-   development NAT Gateway
-   subnet tagging for AWS integrations

### v0.4.2 EKS Baseline

-   Amazon EKS cluster
-   On-Demand Managed Node Group
-   OIDC provider
-   IAM integration
-   EKS managed add-ons
-   EBS CSI IRSA

### v0.4.3 EKS GitOps Bootstrap

-   Argo CD bootstrap
-   AWS Load Balancer Controller with IRSA
-   aws-dev App of Apps
-   demo-api Deployment
-   ALB Ingress exposure

### v0.4.4 Validation and Hardening

-   unified validation workflow
-   safe teardown workflow
-   AWS architecture documentation
-   Terraform output documentation
-   Terraform state guidance
-   troubleshooting runbooks

## v0.5 - Karpenter Autoscaling Baseline

Status: Planned

Goal:

Introduce dynamic node provisioning and workload-aware capacity
management.

Planned scope:

-   Karpenter installation
-   EC2NodeClass configuration
-   NodePool design
-   system and application workload separation
-   scheduling constraints
-   node consolidation
-   Spot capacity optimization
-   interruption handling

## v0.6 - CloudNativePG Data Platform

Status: Planned

Goal:

Introduce Kubernetes-native database operations.

Planned scope:

-   CloudNativePG operator lifecycle
-   PostgreSQL cluster deployment
-   high availability configuration
-   persistent storage
-   backup and restore validation
-   failover testing
-   application database integration

## v0.7 - Production Security Baseline

Status: Planned

Goal:

Add production-oriented security controls.

Planned scope:

-   external secret management
-   AWS Secrets Manager integration
-   TLS and DNS workflow
-   NetworkPolicy
-   Pod Security controls
-   ResourceQuota and LimitRange
-   admission policy validation

## v0.8 - Observability Platform

Status: Planned

Goal:

Build a production observability foundation.

Planned scope:

-   Prometheus production deployment
-   Grafana dashboards
-   Alertmanager
-   centralized logging
-   application SLI/SLO metrics
-   platform health monitoring

## v0.9 - AI Infrastructure Extension

Status: Planned

Goal:

Extend the platform toward AI workloads.

Planned scope:

-   GPU node pool
-   NVIDIA device plugin
-   GPU scheduling and isolation
-   GPU monitoring
-   vLLM inference service
-   OpenAI-compatible API serving
-   model storage workflow

## v1.0 - AIOps Operations Platform

Status: Planned

Goal:

Introduce AI-assisted platform operations.

Planned scope:

-   alert summarization
-   incident triage
-   GitOps diagnosis
-   rollout failure analysis
-   runbook automation
-   human-approved remediation workflows
-   AIOps safety boundaries
