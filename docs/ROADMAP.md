# Roadmap

This roadmap describes the intended evolution of the repository. It is not a fixed delivery schedule.

## v0.1 - Local GitOps Baseline

Status: Completed

Scope:

- kind local Kubernetes cluster.
- Argo CD GitOps control plane.
- App-of-apps root Application.
- demo-api FastAPI workload.
- Helm chart deployment.
- ingress-nginx managed by Argo CD.
- Local ingress access through `demo-api.local`.
- Lightweight Prometheus monitoring.
- One-command validation script.
- Deployment, GitOps, ingress, observability, and troubleshooting documentation.

## v0.2 - CI and Image Validation Baseline

Status: Completed

Goal:

Add a basic CI workflow around the demo API image and Helm chart.

Planned scope:

- GitHub Actions workflow.
- Docker image build.
- Image tag strategy.
- Helm lint/template validation.
- Optional Trivy image scan.
- Optional Hadolint Dockerfile check.
- CI documentation.

## v0.3 - Progressive Delivery

Status: Planned

Goal:

Add safer rollout and rollback patterns.

Planned scope:

- Argo Rollouts.
- Canary or blue-green deployment example.
- Failed release simulation.
- Rollback runbook.
- Release checklist.

## v0.4 - AWS EKS Baseline

Status: Planned

Goal:

Extend the local baseline to AWS EKS.

Planned scope:

- Terraform or OpenTofu infrastructure.
- VPC baseline.
- EKS cluster.
- Managed node group.
- EBS CSI driver.
- AWS Load Balancer Controller.
- IAM integration.

## v0.5 - Autoscaling Baseline

Status: Planned

Goal:

Add node autoscaling with Karpenter.

Planned scope:

- Karpenter installation.
- NodePool and EC2NodeClass.
- On-demand and Spot strategy notes.
- Workload scheduling examples.
- Cost optimization notes.

## v0.6 - Data Layer Baseline

Status: Planned

Goal:

Add a Kubernetes-native Postgres baseline.

Planned scope:

- CloudNativePG operator.
- Postgres cluster example.
- Persistent storage.
- Backup and restore notes.
- Database operation runbook.

## v0.7 - AI Infrastructure Extension

Status: Planned

Goal:

Extend the baseline toward AI infrastructure workloads.

Planned scope:

- OpenAI-compatible inference service example.
- vLLM or similar serving component.
- GPU scheduling notes.
- AI workload monitoring notes.

## v0.8 - AIOps Extension

Status: Planned

Goal:

Add incident-oriented workflows on top of the DevOps baseline.

Planned scope:

- Alert summary workflow.
- Incident triage notes.
- Runbook-based remediation examples.
- Human-in-the-loop operation model.
