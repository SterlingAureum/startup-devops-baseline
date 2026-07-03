# Roadmap

This roadmap describes the intended evolution of the startup-devops-baseline repository.

It is not a fixed delivery schedule. The goal is to keep the repository focused while showing how the local baseline can evolve into a cloud-ready DevOps, GitOps, AI infrastructure, and AIOps reference project.

## v0.1 - Local GitOps Baseline

Status: In progress

Goal:

Build a reproducible local Kubernetes baseline that demonstrates GitOps-based application deployment and basic platform operations.

Current batch:

- kind bootstrap script.
- Argo CD installation script.
- Argo CD root application.
- Local GitOps entrypoint.
- Cleanup script.
- Initial deployment documentation.

Remaining v0.1 scope:

- demo API service.
- Dockerfile.
- Helm chart.
- ingress-nginx.
- basic monitoring.
- validation script.
- deployment and troubleshooting documentation.

Out of scope for v0.1:

- AWS EKS.
- Terraform.
- Karpenter.
- CloudNativePG.
- GPU workloads.
- vLLM or AI model serving.
- Full production security baseline.

## v0.2 - CI and Image Workflow

Status: Planned

Goal:

Add a basic CI workflow for building, tagging, and validating application images.

Planned scope:

- GitHub Actions workflow for demo API image build.
- Image tag strategy.
- Basic container image validation.
- Optional vulnerability scanning.
- CI documentation.
- Local-to-GitOps deployment flow notes.

## v0.3 - Progressive Delivery

Status: Planned

Goal:

Introduce safer deployment patterns and rollback scenarios.

Planned scope:

- Argo Rollouts.
- Canary or blue-green deployment example.
- Failed release simulation.
- Rollback scenario documentation.
- Deployment health validation.
- Release checklist.

## v0.4 - AWS EKS Baseline

Status: Planned

Goal:

Extend the local baseline to a cloud Kubernetes baseline on AWS.

Planned scope:

- Terraform-based AWS infrastructure.
- VPC baseline.
- EKS cluster.
- Managed node group.
- EKS add-ons.
- EBS CSI driver.
- IAM integration.
- Cloud deployment documentation.

## v0.5 - Autoscaling Baseline

Status: Planned

Goal:

Add Kubernetes node autoscaling using Karpenter.

Planned scope:

- Karpenter installation.
- NodePool configuration.
- EC2NodeClass configuration.
- On-demand and Spot strategy notes.
- Workload scheduling examples.
- Cost optimization notes.
- Autoscaling validation scenario.

## v0.6 - Data Layer Baseline

Status: Planned

Goal:

Add a Kubernetes-native Postgres baseline for platform and application data scenarios.

Planned scope:

- CloudNativePG operator installation.
- Postgres cluster example.
- Persistent storage configuration.
- Backup notes.
- Restore scenario.
- Database operation runbook.

Important note:

Running databases on Kubernetes requires a clear storage, backup, restore, and operational strategy. This version should be implemented carefully.

## v0.7 - AI Infrastructure Extension

Status: Planned

Goal:

Extend the baseline toward AI infrastructure workloads.

Planned scope:

- Basic AI inference workload pattern.
- OpenAI-compatible API service example.
- vLLM or similar serving component.
- GPU node scheduling notes.
- AI workload observability notes.
- Cost and capacity planning notes.

## v0.8 - AIOps Extension

Status: Planned

Goal:

Add an AIOps-oriented operations workflow on top of the DevOps baseline.

Planned scope:

- Alert summary workflow.
- Incident triage notes.
- Runbook-oriented remediation examples.
- Log and metric summarization examples.
- Human-in-the-loop operation model.

## Guiding Principles

- Local first, cloud later.
- Stable demo before advanced features.
- Clear documentation before over-engineering.
- GitOps as the deployment model.
- Platform components separated from application workloads.
- Each version should be independently understandable.
- Future features should extend the baseline instead of replacing it.
