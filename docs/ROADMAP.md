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

## v0.11 - Observability and SRE Baseline

Status: In Progress

Goal:

Make the multi-environment platform observable, establish measurable
reliability objectives, and use trusted telemetry to support alerting,
diagnosis, progressive delivery, and operational response.

Incremental scope:

- v0.11.0 - version-boundary correction, environment-aware observability
  architecture, telemetry and correlation conventions, extensible tracing
  foundation, explicit security and automation boundaries, and offline
  positive/negative contract validation - delivered
- v0.11.1 - Prometheus Operator and production-oriented metrics foundation,
  with a pinned kube-prometheus-stack release, ServiceMonitor compatibility,
  system-node placement, NetworkPolicy, and bounded local/AWS storage profiles
  - delivered offline; live local and aws-dev evidence pending
- v0.11.2 - demo-api and platform telemetry, stable resource attributes,
  application-owned ServiceMonitor, Pod-derived release correlation, and
  bounded-cardinality SLI inputs - delivered offline; the local path is
  operator-validated and formal aws-dev evidence remains pending
- v0.11.3 - parameterized local root deployment, safe feature-revision child
  overrides, local-image injection, revision/Chart/ServiceMonitor verification,
  explicit Root OutOfSync semantics, and declarative HEAD restoration - delivered
  offline and live-replayed; repaired by v0.11.3.1 after recovery findings
- v0.11.3.1 - serialize local Argo CD operations, render manual Root mode before
  apply, explicitly remove stale live Helm parameters, enforce the feature
  allowlist, harden HEAD restoration, and document the observed revision 15
  recovery plus demo-api dependency graph - implemented; clean replay exposed
  a Prometheus empty-vector defect repaired by v0.11.3.2
- v0.11.3.2 - add bounded Prometheus metric warm-up, reject empty vectors
  without expression errors, retain fail-closed Canary semantics, and require a
  new clean HEAD-to-feature replay after the revision 22 failure - implemented;
  that replay exposed an Argo CD server-side operation-lock hand-off repaired
  by v0.11.3.3
- v0.11.3.3 - centralize Application operation serialization, retry only the
  exact operation-busy failure with a five-attempt bound, fail all other errors
  immediately, emit exhaustion diagnostics, and execute transient/permanent
  busy regression tests - implemented; the next replay identified the need to
  remove split Root/child source ownership in v0.11.3.4
- v0.11.3.4 - render local child Applications from a Helm App-of-Apps Chart,
  resolve one remote feature input to an immutable commit shared by Root and
  same-repository children, keep external Chart versions independent, and make
  feature image parameters plus HEAD cleanup declaratively Root-owned -
  implemented; pre-merge HEAD restoration exposed a source-schema mismatch
  repaired by v0.11.3.5
- v0.11.3.5 - verify the selected remote revision contains the platform Chart
  before Kubernetes access, separate immutable pre-merge feature restoration
  from post-merge HEAD restoration, and block sync on ComparisonError -
  implemented; complete quality-gate replay exposed historical validator paths
  repaired by v0.11.3.6
- v0.11.3.6 - align namespace guardrail validation with the Helm template and
  stable values model, recursively enforce the local admission-policy boundary,
  and reject both legacy and nested negative fixtures - implemented; complete
  quality-gate and local live recovery accepted
- v0.11.4 - Grafana dashboards, recording rules, and operator-oriented views
  for application, delivery, data, platform, capacity, and cost health - in
  progress
  - v0.11.4.0 - private GitOps-managed Grafana, repository-owned views Chart,
    bounded demo-api recording rules, immutable service overview Dashboard,
    unified feature revision, and local live acceptance - implemented and
    accepted locally; Helm replay exposed historical five-child validation
    repaired by v0.11.4.0.1
  - v0.11.4.0.1 - make the v0.11.3.4 Helm-render regression successor-aware,
    require the sixth observability child and its stable/feature revisions, and
    force the skipped branch through a fake-Helm regression - implemented and
    accepted
  - v0.11.4.1 - delivery, data, and platform views plus version-verified
    controller metrics discovery - in progress
    - v0.11.4.1.0 - observed semantic Argo CD identity, patched and pinned Argo
      Rollouts, repository-owned controller and CloudNativePG monitors,
      Delivery/Data/Platform diagnostic recording rules, and profile-aware
      live discovery - implemented and accepted locally
      - v0.11.4.1.0.1 - stabilize transient Pod discovery and exact Dashboard
        ConfigMap acceptance - implemented and accepted locally
      - v0.11.4.1.0.2 - preserve no-data for absent sources while anchoring
        valid zero numerators to observed request and dependency series -
        implemented and accepted locally
    - v0.11.4.1.1 - immutable Delivery, Data, and Platform Dashboards backed
      only by the accepted v0.11.4.1.0 rules - implemented and accepted locally
  - v0.11.4.2 - capacity and resource-efficiency views, conditional no-data
    hardening, and clean local replay - implemented and accepted locally
    - v0.11.4.2.0 - existing-source capacity and efficiency recording rules,
      bounded request coverage, and profile-aware live discovery - implemented
      and accepted locally
    - v0.11.4.2.1 - immutable Capacity and Resource Efficiency Dashboard backed
      only by the accepted v0.11.4.2.0 rules - implemented and accepted locally;
      clean replay exposed a neutral-baseline image transition and target
      diagnostic defect repaired by v0.11.4.2.2
    - v0.11.4.2.2 - fresh replay image transition, positive target-health
      assertions, shared bounded telemetry preflight, and actionable scrape
      diagnostics - implemented and accepted through one clean local feature replay
- v0.11.5 - Alertmanager routing, actionable alerts, inhibition, severity
  policy, and version-controlled Runbooks with positive/negative drills -
  implemented and accepted locally
  - v0.11.5.0 - environment-local Alertmanager runtime, private exposure,
    bounded persistence, stable severity routing, alert-family inhibition, and
    Prometheus discovery acceptance - implemented offline; local live replay
    proved the runtime configuration and exposed a whitespace-sensitive
    acceptance defect repaired by v0.11.5.0.1
    - v0.11.5.0.1 - accept Alertmanager canonical matcher formatting while
      retaining exact route-and-inhibition matcher cardinality and actionable
      diagnostics - implemented and accepted through the direct local live rerun
  - v0.11.5.1 - eight recording-rule-backed actionable alerts, stable routing
    labels, one reviewed English Runbook per alert, and clean inactive-baseline
    acceptance - implemented and accepted locally
    - v0.11.5.1.1 - repair Prometheus target-down counting with Boolean
      semantics, add the ninth actionable alert and Runbook, and cross-check
      the recorded vector against the direct query - implemented offline;
      local live attempt confirmed fresh-image telemetry and exposed two
      acceptance-path defects repaired by v0.11.5.1.1.1
      - v0.11.5.1.1.1 - correct the diagnostic PrometheusRule ownership name
        and require a unique current-source image after neutral-baseline
        restoration - implemented and accepted locally
  - v0.11.5.2 - firing, routing, inhibition, resolution, and environment-owned
    notification-path drills - implemented and accepted locally
    - v0.11.5.2.0 - guarded local synthetic warning and critical lifecycles,
      continued severity-route assignment, positive and negative inhibition,
      internal webhook firing and resolved delivery, and zero-residual cleanup
      - implemented offline; first local live attempt proved the runtime and
      exposed URL-redaction parser behavior repaired by v0.11.5.2.0.1
      - v0.11.5.2.0.1 - accept exactly two `<secret>` webhook URL lines in the
        active Alertmanager status while retaining exact internal desired-state
        URLs and negative public-URL fixtures - corrected checker accepted
        locally; the resumed drill proved warning firing delivery and exposed
        a delete-before-resolved transition defect repaired by v0.11.5.2.0.2
        - v0.11.5.2.0.2 - retain the same temporary rule and alert identity,
          apply the empty-vector `vector(0) == 1`, wait for Prometheus clearing
          and resolved delivery, then delete only for cleanup; reject active
          drill alerts from earlier failed runs - all four repaired phases
          completed locally; final baseline exposed an asynchronous rule-
          inventory cleanup race repaired by v0.11.5.2.0.3
          - v0.11.5.2.0.3 - make normal Kubernetes cleanup strict and wait
            until both temporary alerts disappear from the Prometheus rule
            inventory before asserting the exact nine formal alerts -
            implemented and accepted through the repaired final local drill
- v0.11.6 - centralized structured logging plus an extensible OpenTelemetry
  tracing foundation for the HTTP to demo-api to PostgreSQL path - in progress
  - v0.11.6.0 - per-environment logging and trace-backend isolation, bounded
    JSON and Loki label contracts, Alloy log/Event ownership, vendor-neutral
    OTLP Collector boundary, minimal Tempo path, implementation sequence, and
    security/cost acceptance boundaries - design-only; implemented offline
  - v0.11.6.1.0 - demo-api one-line JSON runtime, bounded HTTP completion
    records, successful probe-noise suppression, canonical release-identity
    projection through the Downward API, and offline/live application log
    acceptance - implemented; unique local image rerun required
  - v0.11.6.1.1 - local Loki Monolithic and node-local Alloy Pod-log
    collection through the Kubernetes API, with private access, bounded
    resources, 2 GiB disposable storage, 24-hour retention, exact indexed
    labels, NetworkPolicy, application-scoped watcher-exhaustion repair, and
    live replacement persistence acceptance - implemented through
    v0.11.6.1.1.5; local GitOps live validation required
  - v0.11.6.1.2 - singleton Kubernetes Event collection and Grafana Loki data
    source, persistent Event read positions, exact six-label Event streams,
    and restart replay rejection - implemented through v0.11.6.1.2.1, whose
    repair
    co-schedules the WaitForFirstConsumer PVC and consumer Application,
    repairs exact historical render counting, and bounds Argo CD sync waits;
    the acceptance repair series is implemented through v0.11.6.1.2.2, which
    emits API-compatible six-digit Event MicroTime during live acceptance;
    local GitOps live validation required
  - v0.11.6.1.3 closes the local structured-logging runtime with one ordered
    platform, Pod-log, Events, Loki, Grafana, strict-cleanup, retained-history,
    final-state, diagnostic, and consecutive two-run acceptance contract -
    implemented and accepted locally
  - v0.11.6.2.0 adds the demo-api OpenTelemetry contract: W3C propagation,
    bounded HTTP SERVER and PostgreSQL CLIENT spans, shared release identity,
    real JSON log correlation, exact SDK pins, and disabled-by-default OTLP
    export. It deploys no Collector or Tempo; a unique local image rebuild and
    disabled-state acceptance are required.
  - v0.11.6.2.1 adds one private OTel Collector Gateway and one repository-owned
    Tempo 3.0.3 Monolithic runtime. Synthetic OTLP ingest, trace query, private
    service/security controls, and Collector-Pod replacement history are
    accepted independently while demo-api export remains disabled. Local
    reconciliation and consecutive two-run live validation are required; no
    application image rebuild or production durability claim is introduced.
  - v0.11.6.2.1.1 repairs the synthetic OTLP/JSON client to use hexadecimal
    trace and span identifiers, surfaces bounded HTTP error response bodies,
    and selects Collector and Tempo diagnostics explicitly. It changes no
    deployed resource and requires neither reconciliation nor an image rebuild.
  - v0.11.6.2.2 enables the already accepted demo-api exporter only through
    the local App-of-Apps, proves a real `/version` SERVER span and its
    correlated Loki JSON record, and provisions one private Grafana Tempo data
    source plus a Loki `TraceID` derived field. Trace identifiers remain
    unindexed fields; no image rebuild, PostgreSQL trace claim, AWS runtime,
    service graph, span metrics, or durable Tempo storage is introduced.
  - v0.11.6.2.3 closes local minimal tracing with one ordered read-only
    entrypoint, private-Service and Rollout preflight, two independent real
    trace-log correlations, and explicit negative production boundaries. The
    destructive synthetic Collector replacement drill remains independently
    accepted and is not rerun by closure.
  - v0.11.6.2.3.1 repairs runtime artifact preflight so a Synced and Healthy
    neutral replay image cannot be mistaken for the accepted structured-log
    and tracing binary.
- v0.11.7 - service SLOs, error budgets, burn-rate alerts, and SLI-based Argo
  Rollouts analysis gates - implemented and accepted locally
  - v0.11.7.0 establishes 30-day demo-api availability and latency objectives,
    bounded recording rules, remaining-error-budget formulas, one immutable
    Grafana Dashboard, and local semantic acceptance. Burn-rate alerts and
    Rollout decisions remain absent.
  - v0.11.7.0.1 repairs feature replay so a healthy Root or child pinned to an
    older immutable commit is rejected before SLO resource discovery.
  - v0.11.7.1 adds multi-window burn-rate alerting after the formulas are
    accepted.
  - v0.11.7.1.1 repairs cross-filesystem alert-inventory validation without
    changing the accepted v0.11.7.1 runtime.
  - v0.11.7.1.2 repairs the retained live Grafana Dashboard assertion for the
    six-panel burn-rate successor and adds precise API diagnostics.
  - v0.11.7.1.3 repairs the final jq inventory program and adds exact missing
    recording-rule diagnostics without changing runtime state.
  - v0.11.7.2 adds human-governed, exact-release SLO-aware Rollout analysis
  - v0.11.7.2.1 repairs stable-budget PromQL parsing and the local live-traffic race
  - v0.11.7.2.2 repairs stale canary Endpoint identity and pre-scrape traffic timing
  - v0.11.7.3 closes local SLO-aware progressive delivery with explicit policy and evidence
  - v0.11.7.3.1 repairs final Rollout status convergence timing and diagnostics
    with candidate short-window signals and stable 30-day budget protection.
  - v0.11.7.3 closes the SLO phase with ordered end-to-end acceptance.
- v0.11.8 - environment-scoped observability qualification, including an
  approval-protected, read-only aws-prod runtime observation boundary - in progress
  - v0.11.8.0 defines the four-environment capability matrix, portable evidence
    schema, exact environment/revision/release identity lock, resumable
    `waiting-runtime` status, and fail-closed read-only action policy. It makes
    no live AWS qualification claim.
  - v0.11.8.1 implements exact-account/revision/release aws-dev qualification,
    bounded observability read and port-forward RBAC, private Prometheus and
    Alertmanager queries, six Dashboard checks, explicit absent Loki/Tempo
    evidence, idle-SLO semantics, and a trusted-runtime artifact workflow. Live
    acceptance requires an existing reconciled aws-dev environment.
    - v0.11.8.1.1 repairs the historical release-orchestration workflow
      boundary so the contracted aws-dev observability workflow is recognized
      while every arbitrary third AWS/EKS workflow remains rejected.
    - v0.11.8.1.2 qualifies aws-dev from the feature branch with one consistent
      same-repository revision boundary, then restores the dev overlay to main
      before merge.
  - v0.11.8.2 will qualify an exact aws-test release without promoting it.
    - v0.11.8.2.0 defines offline prerequisites and a separate feature preview;
      stable test/prod remain on main. No live bootstrap is enabled.
      - v0.11.8.2.0.1 repairs the Barman Application/Chart identity and makes
        real AWS source manifests an independent validator input.
    - v0.11.8.2.1 supplies guarded feature-mode test execution and independent
      prerequisites, then read-only qualification; live evidence is collected
      separately by the operator, not claimed by offline/package validation.
    Before aws-test live work, resolve its clean-main bootstrap versus feature
    qualification boundary and independently review capacity and credentials.
  - v0.11.8.1.5 closes aws-dev capacity status semantics and bounded node
    readiness waits following the .8.1.3 creation and .8.1.4 scheduling repairs;
    it retains the strict reserve policy and the info58-65 incident record.
  - v0.11.8.3 implements the approval-protected read-only prod observer and
    offline safety tests. Real prod deployment/qualification is deferred to the
    v0.11 tail to avoid running too many clusters simultaneously. Prod stays on
    main; no feature deployment or live qualification is claimed here.
  - v0.11.8.4 will close multi-environment qualification and preserve reviewed
    evidence without rerunning destructive local drills.
    Closure must explicitly retain prod as runtime-deferred until the tail
    checkpoint supplies fresh approved evidence; offline success is not prod success.
- v0.11.9 - clean-room dev/test/prod-live end-to-end release, successful and
  intentionally failed Canary checks, telemetry correlation, reviewed closure
  evidence, environment teardown, and residual-cost audit - planned
  - Sequence environments to limit concurrent cost. At the v0.11 tail, separately
    approve main integration, prod deployment and .8.3 read-only observation.
    Do not claim full prod acceptance before that checkpoint is complete.

v0.11 does not automatically create an EKS environment, merge a pull request,
perform a production Kubernetes write, dispatch a rollback, or remove the
existing production approval boundary. Full remote Terraform state, platform
upgrade lifecycle, recovery objectives, and repository-wide production
readiness remain v0.12 work.

## v0.12 - Production Readiness Capstone

Status: Planned

Goal:

Prove that the complete platform can be rebuilt, upgraded, recovered,
operated, and reviewed as a production-oriented commercial baseline.

Planned scope:

- encrypted remote Terraform state bootstrap and S3-native locking
- state backup, recovery, and operator-access boundaries
- EKS and platform dependency upgrade lifecycle
- clean-room infrastructure and GitOps rebuild
- measured recovery objectives and disaster-recovery review
- production access, break-glass, capacity, availability, and cost review
- repository-wide security, delivery, observability, recovery, and
  documentation acceptance

## v1.0 - Production-ready Commercial Baseline

Status: Planned

Goal:

Stabilize and publish the completed general-purpose DevOps, GitOps, security,
delivery, observability, and SRE baseline without introducing a new workload
domain during release closure.

Planned scope:

- v0.1 through v0.12 architecture and documentation consistency review
- stable supported-version and upgrade matrix
- final commercial deployment, operation, and teardown guidance
- final clean repository, acceptance evidence, and release packaging
- explicit supported, optional, and out-of-scope capability boundaries

## v1.1 - AI Infrastructure Integration

Status: Planned

Goal:

Define how the general platform contracts integrate with the separate
`ai-infra-blueprints` repository without duplicating GPU, model-serving, or
training infrastructure in this repository.

Planned scope:

- cross-repository release, telemetry, SLO, cost, and evidence conventions
- model-serving workload integration contract
- GPU and model identity extension points
- OpenAI-compatible endpoint qualification example
- documented ownership boundary for GPU nodes, NVIDIA components, vLLM,
  model storage, inference benchmarking, and Slurm

## v1.2 - Lightweight AIOps Extension

Status: Planned

Goal:

Introduce AI-assisted, evidence-grounded operations after deterministic
observability, Runbooks, and production-readiness controls are established.

Planned scope:

- alert summarization and evidence correlation
- incident triage and likely-cause ranking
- GitOps and rollout failure diagnosis
- version-controlled Runbook recommendation
- reviewable issue, pull-request, or rollback-handoff preparation
- human-approved remediation workflows
- no direct production mutation, automatic merge, or approval bypass
- AIOps safety, audit, and fallback boundaries
  - v0.11.7.1 adds paired-window availability and latency error-budget burn-rate
    recording rules, four actionable alerts, Runbooks, Dashboard panels, and
    deterministic acceptance without changing progressive delivery decisions.
