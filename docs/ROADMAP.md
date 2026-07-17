# Roadmap

This roadmap describes the intended evolution of the repository. It is not a fixed delivery schedule.

## v0.1 - Local GitOps Baseline

Status: Completed

Delivered:

- kind local Kubernetes cluster;
- Argo CD GitOps control plane;
- app-of-apps root Application;
- demo-api FastAPI workload;
- Helm-based deployment;
- ingress-nginx managed by Argo CD;
- local ingress access through `demo-api.local`;
- lightweight Prometheus monitoring;
- validation and operating documentation.

## v0.2 - CI and Image Validation Baseline

Status: Completed

Delivered:

- GitHub Actions validation;
- Docker image build checks;
- Helm lint and template validation;
- GHCR image publishing foundation;
- image tag and CI workflow documentation.

## v0.3 - Progressive Delivery Baseline

Status: Completed

Delivered across v0.3.0 through v0.3.5:

- Argo Rollouts;
- ingress-nginx canary traffic routing;
- stable and canary Services;
- GHCR image publishing;
- manual GitOps image promotion;
- Prometheus AnalysisTemplate and AnalysisRun;
- promote and abort operations;
- rollback runbook;
- rollout capacity and cost guardrails;
- final local architecture and repository cleanup.

## v0.4 - AWS EKS Infrastructure Baseline

Status: Planned

Goal:

Extend the local baseline to a reproducible AWS EKS development environment.

Planned scope:

- Terraform or OpenTofu project skeleton;
- remote-state-ready environment layout;
- VPC with public and private subnets;
- EKS control plane;
- managed node group;
- EKS add-ons;
- workload IAM foundation;
- EBS CSI driver;
- AWS Load Balancer Controller;
- Argo CD bootstrap;
- `aws-dev` GitOps cluster definition;
- demo-api deployment and validation on EKS;
- cost controls and complete destroy workflow.

## v0.5 - Karpenter Autoscaling Baseline

Status: Planned

Goal:

Add dynamic node provisioning and cost-aware capacity management.

Planned scope:

- Karpenter installation;
- NodePool and EC2NodeClass;
- on-demand base capacity;
- Spot expansion strategy;
- interruption handling;
- consolidation and node expiration;
- workload scheduling examples;
- scaling and cost validation.

## v0.6 - CloudNativePG Data Baseline

Status: Planned

Goal:

Add a Kubernetes-native PostgreSQL baseline.

Planned scope:

- CloudNativePG operator;
- PostgreSQL cluster example;
- EBS-backed persistent storage;
- application database connectivity;
- backup and restore validation;
- disruption and recovery runbook.

## v0.7 - Production Platform Hardening

Status: Planned

Goal:

Add security, policy, secret management, and production operating controls.

Planned scope:

- external secret management;
- AWS Secrets Manager integration;
- TLS and DNS workflow;
- NetworkPolicy;
- Pod Security controls;
- ResourceQuota and LimitRange;
- policy validation;
- expanded metrics, dashboards, and alerting;
- security and operations documentation.

## v0.8 - AI Infrastructure Extension

Status: Planned

Goal:

Extend the platform toward GPU and model-serving workloads.

Planned scope:

- GPU-capable node pool;
- NVIDIA device support;
- GPU scheduling and isolation;
- OpenAI-compatible inference service;
- vLLM or similar serving component;
- model storage and startup workflow;
- inference and GPU monitoring.

## v0.9 - AIOps Extension

Status: Planned

Goal:

Add incident-oriented automation on top of the platform baseline.

Planned scope:

- alert summarization;
- incident triage;
- GitOps and rollout diagnosis;
- runbook mapping;
- human-approved remediation examples;
- AIOps safety boundaries and operating model.
