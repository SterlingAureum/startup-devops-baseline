# Changelog

All notable changes to this repository are documented in this file.

## v0.7.2

### Added

- Metadata-driven aws-dev promotion that validates the source repository,
  source commit, readable SHA tag, immutable OCI digest, and reference before
  changing Git desired state.
- Automatic `release/demo-api-sha-*` branch and pull-request creation after a
  successful main-branch image publish, with idempotent reuse on workflow
  reruns.
- Manual feature-branch validation inputs for explicitly requesting a
  promotion PR against the selected feature branch.
- CI checks for metadata-to-values promotion, digest-pinned Helm rendering,
  and rejection of metadata from an unexpected source commit.

### Changed

- Upgraded checkout, Helm setup, artifact transfer, and Docker Actions to
  Node.js 24 runtime major versions.
- Restricted image-publish path filters to source and build inputs so merging
  a values-only promotion cannot create a recursive publish/promotion loop.
- Scoped build and promotion `GITHUB_TOKEN` permissions per job; promotion can
  write a release branch and pull request but cannot merge or access EKS.

## v0.7.1

### Added

- Helm image-reference helper that renders a registry image by immutable OCI
  digest and rejects malformed digest values.
- Structured demo-api image identity artifact containing the repository, SHA
  tag, digest, source repository, full source commit, and workflow run ID.
- GitHub build-provenance attestation for each published demo-api image,
  attached to the GHCR digest through short-lived OIDC identity.
- CI contract checks for digest-pinned local Rollout and aws-dev Deployment
  rendering and deterministic image identity metadata.

### Changed

- Extended all active demo-api Helm values with an explicit `image.digest`
  field while preserving tag-only local-image fallback.
- Made registry-image promotion require both the human-readable SHA tag and
  immutable digest.
- Extended GHCR image verification to prove that the supplied tag resolves to
  the expected digest.
- Recorded the published image identity as a retained GitHub Actions artifact
  and workflow summary for the future promotion workflow.

## v0.7.0

### Added

- Reusable GitHub Actions quality-gate workflow shared by pull-request
  validation and demo-api image publishing.
- Containerized demo-api unit-test stage covering process health, service
  identity, database-aware readiness, sanitized dependency failures, metrics,
  environment parsing, and bounded retry behavior.
- Local `validate-ci-quality-gates.sh` entry point for shell syntax, local and
  aws-dev Helm rendering, unit tests, and final image build validation.
- Per-workflow concurrency, least-privilege read permissions, and bounded job
  timeouts for the CI validation path.

### Changed

- Made GHCR image publishing depend explicitly on the reusable quality gates.
- Converted the demo-api Dockerfile to test and runtime stages while preserving
  the same final runtime command and image behavior.
- Removed the completed `feature/v0.4-aws-eks-baseline` branch from Terraform
  workflow triggers.
- Reordered the roadmap so GitOps promotion follows quality gates before the
  production security, observability, AI infrastructure, and AIOps stages.

## v0.6.5

### Added

- PostgreSQL integration for demo-api through the CloudNativePG-generated
  application identity and `postgresql-baseline-rw` Service.
- Sanitized `/db/health` endpoint, database-aware readiness, bounded connection
  retries, and an internal marker CLI without a public database write endpoint.
- Minimum cross-namespace Secret synchronization that copies only `fqdn-uri`
  into `startup-apps/demo-api-postgresql` without printing or committing the
  credential.
- Non-disruptive validation for the Secret contract, Deployment environment,
  RW Service endpoint, current primary, and every demo-api replica.
- Guarded primary-Pod failover drill covering replica promotion, RW Service
  movement, application reconnection, committed-data preservation,
  post-failover writes, and former-primary PVC/PV/EBS reuse.

### Changed

- Moved the aws-dev demo-api Argo CD Application after the PostgreSQL
  Application with sync wave `30`.
- Extended AWS deployment, validation, cleanup, architecture, environment, and
  roadmap documentation for the application database lifecycle.
- Corrected the backup preparation script's stray Markdown fences and removed
  the duplicate deployment-document sentence.

## v0.6.4

### Added

- Isolated `database-recovery-ondemand` NodePool with a one-node On-Demand
  ceiling, database recovery taint, and empty-node consolidation.
- Guarded latest-state restore and point-in-time recovery drill using the
  Barman Cloud CNPG-I plugin and the existing S3 backup archive.
- Deterministic marker workflow that proves the latest restore contains all
  archived writes while PITR preserves pre-target data and excludes a
  post-target transaction.
- Recovery cleanup validation for temporary CloudNativePG Clusters, PVCs, EBS
  volumes, NodeClaims, and EC2 nodes.
- Non-disruptive readiness validator for the source cluster, completed
  backups, shared IRSA ServiceAccount, recovery NodePool, and clean idle state.

### Changed

- Recovery clusters use CloudNativePG 1.30 shared `serviceAccountName` support
  to reuse the existing narrowly scoped IRSA role without widening IAM trust.
- Applied the validated v0.6.3 Barman sidecar memory, concurrency, plugin
  enabled-state, Deployment-name, and image-version corrections to the
  version baseline.
- Extended unified validation, Karpenter NodePool checks, architecture,
  deployment, cleanup, and roadmap documentation for the recovery lifecycle.

## v0.6.3

### Added

- Terraform-managed, versioned, encrypted, public-access-blocked S3 bucket for
  PostgreSQL physical backups and WAL archives.
- Least-privilege IRSA role scoped to the CloudNativePG cluster
  ServiceAccount and the database-specific S3 prefix.
- GitOps-managed cert-manager `v1.21.0` and Barman Cloud CNPG-I plugin
  `0.13.0` through official pinned Helm charts.
- Barman `ObjectStore` with IRSA authentication, lz4 compression, bounded
  parallelism, sidecar resources, and a seven-day recovery window.
- Daily plugin-based `ScheduledBackup` and continuous WAL archiving from the
  existing three-instance PostgreSQL cluster.
- Runtime backup test and validation for IAM, S3 security, plugin health,
  ObjectStore configuration, completed base backups, and S3 WAL objects.

### Changed

- `deploy-aws-dev-root-app.sh` now annotates the database ServiceAccount with
  the Terraform role and renders the live S3 destination without committing
  environment-specific values.
- Added explicit backup deletion confirmation to the full AWS destroy path.
- Updated architecture, deployment, outputs, cleanup, rollback, and roadmap
  documentation for the v0.6.3 backup lifecycle.

## v0.6.2

### Added

- Dedicated `database` EC2NodeClass with private networking, IMDSv2, encrypted
  gp3 root storage, and the existing Karpenter node role.
- Bounded `database-ondemand` NodePool with a database-only taint, three-node
  ceiling, two-AZ constraints, and empty-node-only consolidation.
- Three-instance CloudNativePG topology with one primary, two replicas,
  required hostname anti-affinity, and balanced two-AZ spreading.
- Quorum-style synchronous replication requiring one standby acknowledgement
  for committed transactions.
- Runtime validation for database NodeClaims, instance roles, node and AZ
  placement, three PVC/PV/EBS chains, services, and live replication state.
- Guarded replica-recreation test that proves the primary remains stable while
  the replica reuses its PVC, PV, and EBS volume.

### Changed

- Scoped application scale tests and idle-capacity validation by NodePool so
  persistent database NodeClaims are not mistaken for leaked test capacity.
- Extended Karpenter validation to the database EC2NodeClass and NodePool.
- Updated cleanup warnings, architecture, deployment, environment, destroy,
  rollback, and roadmap documentation for the HA database topology.

## v0.6.1

### Added

- GitOps-managed single-instance CloudNativePG `Cluster` pinned to PostgreSQL
  `17.10` by immutable image digest.
- Dedicated `data-platform` namespace and encrypted `gp3-cnpg` StorageClass
  with a 20Gi EBS data volume, volume expansion, and delayed binding.
- Explicit 500m CPU and 1Gi memory Guaranteed resource contract on stable
  `workload=system` nodes.
- Non-disruptive runtime validation for the Application, Cluster, generated
  credential Secret, Pod placement, PVC, PV, EBS encryption, and database
  connection.
- Guarded Pod-recreation test that writes a marker and proves reuse of the same
  PVC, PV, and EBS volume.

### Changed

- Extended unified validation to include the PostgreSQL persistence baseline
  without restarting the database.
- Disabled automated pruning for database-owned resources and added
  dependency-aware PostgreSQL storage cleanup before EKS destruction.
- Updated AWS architecture, deployment, environment, rollback, destroy, and
  roadmap documentation for the first stateful workload.

## v0.6.0

### Added

- Argo CD Application for the official CloudNativePG Helm chart, pinned to
  chart `0.29.0` and CloudNativePG `1.30.0`.
- Two operator replicas constrained to the stable `workload=system` Managed
  Node Group and spread across different nodes.
- Runtime validation for the Argo CD Application, core CRDs, admission
  webhooks, operator rollout, replica count, node placement, and operator-only
  release boundary.
- CloudNativePG operator architecture, deployment, environment, and version
  documentation.

### Changed

- Advanced active aws-dev Git revisions to
  `feature/v0.6-cloudnativepg-data-platform`.
- Marked the v0.5 roadmap complete after the validated AWS FIS interruption
  drill.
- Corrected stale local architecture and rollback descriptions.
- Included the FIS smoke namespace in the standalone aws-dev cleanup workflow.

## v0.5.5

### Added

- Terraform-managed AWS FIS experiment role and tag-scoped Spot interruption
  template.
- Dedicated `application-fis` EC2NodeClass whose EC2 tags isolate the
  experiment target from normal application nodes.
- Dedicated `application-spot-fis` NodePool with a distinct taint and a
  two-node ceiling that permits proactive replacement.
- Runtime validation for the FIS IAM trust, least-privilege actions, experiment
  template, target tag, and Kubernetes capacity contract.
- Guarded real-interruption drill that validates target cardinality before
  starting FIS, replacement Spot capacity, Pod rescheduling, original-instance
  termination, NodeClaim cleanup, and consolidation-driven scale-in.

### Changed

- Extended unified validation to cover the AWS FIS foundation without starting
  an experiment.
- Extended aws-dev cleanup for the FIS smoke namespace.
- Added precise Terraform ignore rules for `tfplan` and `*.tfplan` without
  using a broad plan-name pattern.
- Updated Karpenter architecture, deployment, environment, output, destroy, and
  roadmap documentation.

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
