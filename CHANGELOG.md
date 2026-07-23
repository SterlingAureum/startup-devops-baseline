# Changelog

All notable changes to this repository are documented in this file.

## v0.5.4

### Added

- GitOps-managed `application-spot` NodePool with a dedicated workload taint.
- Broad Spot instance-category, generation, and vCPU constraints with bounded
  CPU, memory, and node count.
- Controlled Spot scale test that verifies both Kubernetes capacity labels and
  the EC2 `InstanceLifecycle` value.
- Runtime interruption-readiness validation for the Karpenter controller,
  encrypted SQS queue, Spot EventBridge rule, and queue target.

### Changed

- Added explicit `capacity-tier=on-demand` labeling to the existing On-Demand
  NodePool.
- Extended unified validation to cover both NodePools and the interruption
  event path without provisioning capacity.
- Updated cleanup and destroy workflows for both Karpenter smoke namespaces.
- Updated Karpenter architecture, deployment, environment, and roadmap
  documentation.

## v0.5.3

### Added

- GitOps-managed `application-ondemand` NodePool for isolated application
  capacity.
- On-Demand, architecture, operating-system, instance-family, generation, and
  vCPU scheduling constraints.
- CPU, memory, and node-count safety limits with consolidation enabled.
- Controlled scale test that provisions one temporary application node,
  validates NodeClaim and node labels, removes the workload, and waits for
  scale-in.
- Dedicated NodePool readiness and idle-capacity validation.

### Changed

- Extended unified validation with the On-Demand NodePool baseline without
  creating EC2 capacity.
- Updated cleanup and destroy workflows to remove NodePools, NodeClaims, and
  Karpenter nodes before the EC2NodeClass and controller.
- Updated Karpenter architecture, deployment, environment, and roadmap
  documentation.

## v0.5.2

### Added

- GitOps-managed `application` EC2NodeClass for future Karpenter NodePools.
- AL2023 AMI, private-subnet, cluster-security-group, and node-role discovery.
- Explicit IMDSv2, encrypted gp3 root volume, private-addressing, and EC2 tag
  settings for future application nodes.
- EC2NodeClass readiness, Terraform role-contract, discovery, and no-provisioning
  validation.
- Dependency-aware EC2NodeClass and generated instance-profile cleanup.

### Changed

- Extended unified validation with the EC2NodeClass discovery baseline.
- Updated Karpenter architecture, deployment, environment, output, and roadmap
  documentation.

## v0.5.1

### Added

- Argo CD Applications for the Karpenter 1.14.0 CRDs and controller.
- Karpenter controller IRSA ServiceAccount bootstrap.
- Dedicated validation for Karpenter Applications, CRDs, IRSA, rollout, and
  controller placement.
- GitOps ownership notes for environment-specific Application rendering.

### Changed

- Rendered the AWS Load Balancer Controller VPC ID from Terraform output during
  bootstrap instead of committing a real VPC ID.
- Pinned Karpenter controller pods to the stable `workload=system` Managed Node
  Group.
- Updated the aws-dev Git revisions and deployment script to
  `feature/v0.5-karpenter-autoscaling`.
- Extended the unified AWS validation workflow with Karpenter controller
  validation.

## v0.5.0

### Added

- Dedicated Terraform module for the Karpenter AWS foundation.
- Karpenter controller and node IAM roles.
- Six scoped Karpenter 1.14 controller IAM policies.
- EKS access entry for Karpenter-provisioned Linux nodes.
- Encrypted SQS interruption queue and five EventBridge rules.
- Discovery tags for private subnets and the EKS cluster security group.
- Terraform outputs and AWS foundation validation script.

### Changed

- Pinned the EKS development environment to Kubernetes 1.36.
- Reserved two On-Demand Managed Node Group nodes for system controllers.
- Changed the Managed Node Group workload label from `general` to `system`.

## v0.4.4

### Added

- Unified AWS validation workflow.
- Safe AWS environment teardown workflow.
- AWS architecture and environment documentation.
- Terraform output and state-management guidance.
- Troubleshooting documentation based on actual EKS deployment issues.

### Changed

- Explicitly configured the VPC ID for AWS Load Balancer Controller.
- Kept worker-node IMDSv2 response hop limit at 1.
- Updated the repository documentation for local and AWS environments.

## v0.4.3

### Added

- Argo CD bootstrap for Amazon EKS.
- AWS Load Balancer Controller with IRSA.
- `aws-dev` App of Apps.
- demo-api Deployment and ALB Ingress.

## v0.4.2

### Added

- Amazon EKS control plane.
- On-Demand Managed Node Group.
- EKS managed add-ons.
- OIDC provider and workload IAM roles.

## v0.4.1

### Added

- Multi-AZ VPC network.
- Public and private subnets.
- Internet Gateway and development NAT Gateway.
- EKS and load-balancer subnet tags.

## v0.4.0

### Added

- Terraform environment and module structure.
- AWS provider configuration.
- Terraform validation workflow.

## v0.3

### Added

- Argo Rollouts progressive delivery.
- Canary routing with ingress-nginx.
- GHCR image publishing.
- Prometheus-based rollout analysis.
- Promotion, abort, and rollback workflows.

## v0.2

### Added

- GitHub Actions validation.
- Docker image build checks.
- Helm lint and template validation.

## v0.1

### Added

- kind Kubernetes baseline.
- Argo CD App of Apps.
- Helm-based demo-api deployment.
- ingress-nginx and lightweight monitoring.
