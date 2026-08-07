# Changelog

All notable changes to this repository are documented in this file.

## v0.9.6

### Added

- Guarded create/resume Terraform entrypoint and environment-aware GitOps
  bootstrap for the ephemeral aws-test clean-room environment.
- Reviewed aws-test Rollout completion and runtime validation entrypoints that
  retain the restricted local EKS access boundary.
- Generalized dependency-aware aws-dev/aws-test teardown with an explicit
  aws-prod refusal and environment-specific confirmation phrase.
- Post-destroy AWS residual audit for Terraform state, EKS, VPC, EC2, EBS,
  NAT Gateway, Elastic IP, S3, Secrets Manager deletion state, CloudWatch,
  ACM, Route 53, and currently tagged regional resources.
- Final v0.9.6 evidence writer, validator, tamper behavior tests, and protected
  evidence path binding dev/test qualification to one immutable artifact.
- Clean-room lifecycle and failure-recovery runbook plus the v0.9.6 checkpoint
  document.

### Changed

- Allowed the shared AWS root deployment helper to accept an explicit set of
  reviewable Argo CD health states while preserving Healthy-only aws-dev
  behavior by default.
- Kept aws-test ephemeral and aws-prod static-only for v0.9 acceptance instead
  of requiring three concurrently running portfolio clusters.
- Added lifecycle, cleanup, and final-evidence behavior to the reusable CI
  quality gate. Live AWS execution remains a separate operator acceptance step.

## v0.9.5

### Added

- GitOps-managed Argo Rollouts in the reusable AWS platform base and ALB
  weighted canary delivery for aws-test and aws-prod.
- Environment-specific test and production canary steps with bounded surge,
  zero intentional unavailability, Web AnalysisRun readiness/database/release
  identity checks, and manual progression gates.
- Local restricted-EKS runtime evidence collection plus strict v0.9.5 evidence
  writing, validation, freshness, release binding, and tamper behavior tests.
- Static contracts for ALB action routing, Rollout-managed Argo CD fields,
  AnalysisRun release identity, and the AWS progressive-delivery profiles.
- A least-privilege NetworkPolicy path from the Argo Rollouts controller to
  demo-api port 8080 for canary-local Web analysis.

### Changed

- Required cross-environment Promotion PRs to cite both the existing reviewed
  static evidence and a fresh, reviewed AWS runtime record from `main`.
- Preserved aws-dev as the already validated Deployment baseline while
  enabling progressive delivery only in aws-test and aws-prod.
- Kept GitHub-hosted evidence, promotion, and rollback jobs outside EKS; live
  evidence is collected locally because the Kubernetes API remains restricted.

## v0.9.4

### Added

- Manual source-release qualification workflow for aws-dev and aws-test that
  verifies release schema, Helm rendering, and exact GHCR digest availability,
  then creates a reviewable machine-readable evidence PR.
- Strict v0.9.4 evidence schema and freshness validation bound to the current
  source release SHA-256, source environment, evidence run ID, immutable image,
  source commit, and original build workflow identity.
- CODEOWNERS boundaries for demo-api release records, evidence, delivery
  workflows, and the scripts that mutate or validate release state.
- Promotion and rollback jobs protected by target GitHub Environments, plus
  local behavior tests for evidence tampering, staleness, expiration, approval
  contracts, and dev/test/prod rollback isolation.

### Changed

- Required every aws-dev to aws-test and aws-test to aws-prod Promotion PR to
  cite reviewed, unexpired source evidence already present on `main`.
- Generalized the GitOps rollback workflow from aws-dev to aws-dev, aws-test,
  and aws-prod while preserving historical target-release-only restoration,
  immutable artifact verification, stale-main rejection, PR review, and zero
  direct EKS access.
- Kept v0.9.4 evidence explicitly static; AWS rollout and AnalysisRun runtime
  evidence remains part of v0.9.5.

## v0.9.3

### Added

- Manual ordered environment promotion workflow for aws-dev to aws-test and
  aws-test to aws-prod, with invalid skipped, reverse, and same-environment
  transitions rejected before mutation.
- Strict release-copy helper that preserves the exact image digest, readable
  tag, application version, source commit, source repository, and build
  workflow identity while changing only the target release file.
- Digest-addressed GHCR artifact existence verification, target-environment
  concurrency groups, and fail-closed stale-main checks before branch push and
  PR creation.
- Local behavior and workflow-contract validation for allowed and denied
  transitions, invalid digests, stale source snapshots, permissions, PR-only
  behavior, and release-path isolation.

### Changed

- Extended the build-once delivery chain from the existing build to aws-dev PR
  into the ordered aws-dev to aws-test to aws-prod model without granting
  GitHub Actions access to EKS or automatic merge authority.
- Added the ordered promotion contract to the reusable CI quality gate and
  updated the active multi-environment delivery documentation.

## v0.9.2

### Added

- Independent dev, test, and prod Terraform roots with non-overlapping VPC and
  EKS Service CIDRs, unique cluster/DNS/Secret/backup identities, and separate
  local state boundaries.
- Reusable AWS Kustomize base plus dev/test/prod overlays for platform,
  CloudNativePG, External Secrets, and NetworkPolicy declarations.
- Static environment-isolation validation and three-environment Kustomize
  rendering in the reusable quality gate.
- Production fail-closed validation requiring multi-AZ NAT, 90-day control-plane
  logs, a non-destructive backup bucket, and a 30-day Secret recovery window.

### Changed

- Migrated the active aws-dev GitOps source from `clusters/aws-dev` to the dev
  overlay while preserving its resource identities and runtime configuration.
- Extended Terraform validation from dev only to dev, test, and prod.
- Excluded AWS FIS infrastructure and FIS-only Karpenter capacity from the
  production declaration.

## v0.9.1

### Added

- Separate Helm environment and release values for aws-dev, aws-test, and
  aws-prod, with static rendering profiles for environments not yet created.
- A values-ownership contract that rejects artifact identity in environment
  files, runtime configuration in release files, invalid delivery identity,
  legacy mixed aws-dev values, and incorrect Argo CD value-file ordering.
- Three-environment Helm lint and rendering coverage in the reusable quality
  gate without creating AWS resources.

### Changed

- Made the active aws-dev Argo CD Application load environment configuration
  first and release identity second while preserving the existing rendered
  Deployment behavior.
- Restricted metadata-driven image promotion and history-based rollback to
  `values/releases/aws-dev.yaml`; hostname, resources, ingress, Secret, and
  database settings remain outside the automation diff.
- Moved readable application version ownership from `env.APP_VERSION` to
  `release.applicationVersion` and continued rendering it as the workload
  `APP_VERSION` environment variable and delivery annotation.
- Removed the mixed `apps/demo-api/helm/values-aws-dev.yaml` source of truth.

## v0.9.0

### Added

- Accepted multi-environment GitOps design contract for one independent EKS
  cluster per AWS environment: `aws-dev`, `aws-test`, and `aws-prod`.
- Ordered build-once promotion model that permits only build to aws-dev,
  aws-dev to aws-test, and aws-test to aws-prod while retaining the same
  immutable application digest.
- Explicit isolation rules for Terraform state, AWS accounts, VPCs, clusters,
  Argo CD installations, credentials, databases, backups, certificates, and
  DNS identities.
- Static active-revision validation that classifies every internal-repository
  Argo CD Application and rejects feature-branch revisions from active cluster
  and validation contracts.
- Multi-environment architecture and v0.9.0 checkpoint documentation, including
  the cost-aware sequential validation model and later target directory shape.

### Changed

- Converged the seven active aws-dev child Applications and their security
  contract validators from the completed v0.8 feature branch to `main`.
- Marked v0.8 complete and moved the former observability roadmap scope to
  v1.0 so v0.9 can focus on multi-environment promotion.
- Expanded the environment model to distinguish current deployed state from
  the v0.9 target architecture and its per-environment lifecycle.

## v0.8.6

### Added

- Terraform-managed DNS-validated ACM certificate for
  `demo.dev.aureumstack.com` in the existing public `aureumstack.com` Route 53
  hosted zone.
- HTTPS ALB listener, TLS 1.2/1.3 security policy, stable host routing, and
  HTTP-to-HTTPS redirect for the aws-dev demo-api Ingress.
- Guarded dynamic management-IP updater that passes the current public `/32`
  directly to Terraform without writing it to a tracked or local repository
  file.
- Idempotent Route 53 Alias reconciliation from the live Kubernetes Ingress and
  ALB canonical hosted-zone identity.
- Security-relevant EKS `api`, `audit`, and `authenticator` control-plane logs
  with Terraform-managed 14-day CloudWatch retention.
- Static public-IP privacy and TLS/DNS security contracts plus a live final
  validator for EKS endpoint access, logging, ACM, Route 53, redirect, TLS
  identity, HTTPS application health, Argo CD convergence, and the completed
  PostgreSQL credential rollback state.

### Changed

- Made the public EKS endpoint allowlist fail closed by default and rejected
  `0.0.0.0/0` in both environment validation and the EKS resource lifecycle.
- Made the guarded endpoint updater create its disposable saved plan with
  owner-only permissions, refresh kubeconfig after the EKS update, and prove
  Kubernetes API readiness before reporting success.
- Made the aws-dev root deployment refresh and verify kubeconfig before its
  first Kubernetes operation, wait for a replacement ALB, and idempotently
  reconcile the stable Route 53 Alias after every deployment.
- Made credential bootstrap preserve a distinct existing `AWSCURRENT` only
  after proving that it authenticates to the current PostgreSQL primary, so a
  branch revision change cannot overwrite or reject a valid rotated credential.
- Removed temporary ExternalSecret `force-sync` annotations after successful
  deployment and Secret reconstruction, with best-effort exit cleanup to keep
  later credential activation guards unblocked.
- Moved live AWS TLS/DNS validation ahead of credential-drill final-state
  validation so stale post-rebuild Alias state is reported directly, and added
  an explicit diagnostic for a rebuilt Secret that still has only
  `AWSCURRENT`.
- Changed aws-dev application and NetworkPolicy health checks from direct ALB
  HTTP access to the stable verified HTTPS hostname.
- Added Route 53 Alias cleanup before ALB deletion while retaining domain
  registration and the public hosted zone outside the disposable environment.

## v0.8.5

### Added

- Guarded generation of a high-entropy PostgreSQL credential candidate stored
  only under the Secrets Manager `AWSPENDING` stage.
- Read-only AWS validation proving that the candidate differs only by password
  while `AWSCURRENT`, the CNPG source Secret, the ESO target Secret, and the
  active ExternalSecret contract remain unchanged.
- Guarded candidate discard that removes only the `AWSPENDING` label without
  deleting the Secret container or moving `AWSCURRENT`.
- Static rotation contracts that prohibit database mutation, External Secrets
  refresh, and workload restart during candidate staging.
- Guarded candidate activation that changes the PostgreSQL role through
  protected standard input, promotes version stages, forces ESO convergence,
  and removes its temporary reconciliation annotation.
- One-at-a-time Deployment Pod replacement with per-Pod credential-digest and
  PostgreSQL primary-connectivity checks.
- Automatic partial-cutover compensation that restores the original database
  password, `AWSCURRENT`, ESO target Secret, and workload credential while
  retaining the candidate under `AWSPENDING` for investigation or retry.
- Read-only Checkpoint 2 AWS validation for `AWSCURRENT`/`AWSPREVIOUS` stage
  isolation, authentication behavior, Pod environment convergence, GitOps
  health, and application connectivity.
- Guarded `AWSPREVIOUS` rollback and forward-recovery drill that changes the
  real PostgreSQL role, moves Secrets Manager stages, converges ESO, and reloads
  each demo-api Pod in both directions before restoring the Checkpoint 2 state.
- Intermediate rollback validation proving that only the restored credential
  authenticates and every Pod loaded it before forward recovery begins.
- Automatic drill recovery that restores the starting PostgreSQL password,
  version stages, ESO target, and workload Pods after a failed rollback or
  forward transition.
- Read-only Checkpoint 3 final-state validation that reuses the full Checkpoint
  2 invariant set after the transient rollback evidence has been produced by
  the guarded drill.

### Changed

- Allowed guarded activation and compensation reloads to accept original Pods
  that remain Running but become NotReady after the single PostgreSQL password
  changes, while preserving strict Ready, credential-digest, and database
  health checks for every replacement Pod.
- Aligned the Checkpoint 1 AWS validator with activation by rejecting a stale
  ExternalSecret `force-sync` annotation before any database mutation.
- Split credential rotation into a no-impact candidate-staging checkpoint and
  a guarded, automatically compensated cutover checkpoint so the unavoidable
  single-password transition remains bounded and observable.
- Made AWS Secrets Manager `AWSCURRENT` plus the ESO target Secret the active
  credential chain after initial migration; the CloudNativePG-generated Secret
  remains a legacy bootstrap artifact after the first external rotation.
- Aligned PostgreSQL application validation and future candidate staging with
  the active external credential chain instead of requiring equality with the
  now-historical CNPG Secret.

## v0.8.4

### Added

- Guarded, idempotent migration of the CloudNativePG application URI into the
  `DATABASE_URL` property of the Terraform-managed AWS Secrets Manager Secret.
- Active namespaced ExternalSecret reconciliation for the existing
  `startup-apps/demo-api-postgresql` contract.
- Runtime validation for exact-secret IAM denial, protected-value equality,
  target Secret deletion and automatic reconstruction, and application
  connectivity through the current PostgreSQL primary.

### Changed

- Retired cross-namespace Kubernetes Secret copying from the normal deployment
  path and retained it only as an explicitly guarded break-glass workflow.
- Declared ExternalSecret CRD defaults explicitly to keep Argo CD
  `Synced / Healthy` after API-server normalization.
- Migrated PostgreSQL Service validation and failover diagnostics from the
  deprecated core `v1 Endpoints` API to `discovery.k8s.io/v1` EndpointSlice.

## v0.8.3

### Added

- Terraform-managed AWS Secrets Manager container without a Secret version,
  plus an exact-secret IRSA role for External Secrets Operator.
- Argo CD-managed External Secrets Operator `2.8.0`, namespace-scoped RBAC, and
  the namespaced `startup-apps/aws-secrets-manager` SecretStore.

### Changed

- Made the data-platform NetworkPolicy rebuild-portable with an explicit EKS
  Service CIDR, permanent CloudNativePG join policies, and live endpoint
  validation after disposable cluster recreation.

## v0.8.2

### Added

- Amazon VPC CNI NetworkPolicy enforcement with managed add-on, node-agent,
  PolicyEndpoint, and isolated allow/deny/allow runtime validation.
- GitOps-managed default-deny and explicit allow policies for `startup-apps`,
  covering DNS, public-ALB ingress, and demo-api access to the baseline
  PostgreSQL cluster.
- GitOps-managed default-deny and explicit CloudNativePG policies for
  `data-platform`, covering operator control, replication, PostgreSQL Service,
  Barman plugin, Kubernetes API, S3, STS, and recovery Job traffic.
- Static policy-contract checks and AWS runtime matrices for live subnet,
  Service ClusterIP, Kubernetes API endpoint, database, WAL archival, and
  unauthorized-traffic behavior.

### Changed

- Restricted ALB ingress to the live ELB-tagged public subnet CIDRs and
  validated policy alignment against the deployed load balancer.
- Restricted internal Service paths to live `/32` addresses instead of opening
  the entire Kubernetes Service CIDR.
- Extended the CloudNativePG recovery drill to detect failed recovery Jobs,
  preserve diagnostics before cleanup, and wait only for database instance
  Pods when evaluating readiness.
- Revalidated backup, primary failover, latest-state recovery, PITR, data
  integrity, and recovery-resource cleanup while default-deny enforcement was
  active.

## v0.8.1

### Added

- GitOps-managed namespace guardrails for `startup-apps` and `data-platform`,
  including Pod Security Admission, ResourceQuota, and LimitRange controls.
- Kubernetes-native ValidatingAdmissionPolicy and CEL enforcement for
  application Pods and common workload-controller Pod templates.
- Immutable `sha256` image-digest requirements for containers and init
  containers in protected application namespaces.
- Explicit CPU and memory request and limit requirements for
  workload-controller Pod templates, with LimitRange defaults retained as a
  safety fallback for directly created Pods.
- Repository contract checks and AWS runtime admission tests covering
  compliant requests, privileged Pods, mutable image tags, missing resource
  declarations, LimitRange default injection, and namespace-scope isolation.

### Changed

- Enforced the `restricted` Pod Security Standard for `startup-apps` and staged
  `data-platform` with `baseline` enforcement plus `restricted` warnings and
  audit records.
- Scoped application admission-policy bindings to namespaces labeled
  `platform.startup.dev/tier=application`, keeping operator-managed
  CloudNativePG workloads outside the generic application policy.
- Hardened AWS admission validation to refresh the Argo CD Application and
  wait for the intended Git revision before evaluating live policy behavior.

## v0.8.0

### Added

- Gitleaks full-history secret scanning in the reusable pull-request and
  publishing quality gates.
- Trivy HIGH/CRITICAL misconfiguration gate for the demo-api Docker and Helm
  configuration.
- Pre-publication Trivy image gate that blocks fixable HIGH/CRITICAL operating
  system and application-library vulnerabilities.
- SPDX JSON SBOM generation, retained workflow artifact, and digest-bound
  registry attestation for every published demo-api image.
- Supply-chain contract validation covering immutable Action pins, scan
  thresholds, pre-push ordering, digest resolution, attestations, and Promotion
  PR dependencies.

### Changed

- Hardened the demo-api image and Kubernetes workload for non-root execution,
  a read-only root filesystem, dropped capabilities, RuntimeDefault seccomp,
  disabled ServiceAccount token automounting, and a bounded memory-backed
  `/tmp`.
- Pinned every external GitHub Action to a reviewed full commit SHA while
  retaining readable release-version comments.
- Changed image publishing to build and load a local security candidate first;
  GHCR login and push occur only after the image scan and SBOM generation
  succeed.
- Made build provenance, SBOM attestation, and the complete scanned-image job
  mandatory predecessors of the aws-dev Promotion PR.

## v0.7.4

### Added

- Manual demo-api GitOps rollback workflow that restores a selected historical
  aws-dev release through a reviewable values-only pull request.
- Historical desired-state validator requiring an ancestor commit, a
  values-only release diff, immutable image digest, matching SHA tag and
  application version, full source commit, and build workflow identity.
- CI rollback fixtures covering exact historical restoration, idempotency,
  change isolation, invalid-target rejection, manual-only workflow triggering,
  and the no-EKS-access boundary.
- Final promotion and rollback exercise that verifies Git, Argo CD, Deployment,
  Pod image ID, and `/version` all converge on the selected release.

### Changed

- Generalized the live trace input from `PROMOTION_REVISION` to
  `DESIRED_REVISION` so the same read-only validator covers promotion and
  rollback commits. The former variable remains a compatibility alias.
- Finalized the v0.7 CI/CD and GitOps promotion baseline while retaining human
  approval and Argo CD as the environment-change boundaries.

## v0.7.3

### Added

- Delivery metadata values for the source repository, full source commit, and
  image-build workflow run ID.
- Workload and Pod annotations that expose the readable image tag, immutable
  digest, application version, source identity, and build run without exposing
  credentials.
- Read-only delivery trace validator covering source commit, image tag and
  digest, values-only promotion commit, Argo CD sync revision, Deployment
  identity, every Pod image ID, and every `/version` response.
- CI checks for delivery-metadata insertion, idempotent updates, and rendered
  Deployment/Pod trace annotations.

### Changed

- Extended metadata-driven Promotion PRs to retain build origin in the same
  `values-aws-dev.yaml` change.
- Made `app.kubernetes.io/version` reflect `env.APP_VERSION` instead of the
  static chart application version.

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
