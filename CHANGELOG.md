# Changelog

## v0.11.8.2.1.1

- Register the exact offline test feature preview in the historical active
  GitOps inventory and revision check; retain all other feature restrictions.
- Validate its complete source, identity, destination and no-auto-sync shape.
- Add positive/predecessor and 13 negative regression cases; run the real
  historical gate from the .8.2.1 focused validator as well as full CI.
- No runtime manifests, deployment scripts or cloud resources are changed.

## v0.11.8.2.1

- Add fixed-target aws-test feature plan/apply/bootstrap with exact pushed
  revision/account guards, explicit capacity profile and separate saved-plan
  review; reject automatic deletion/replacement and foreign-root takeover.
- Prepare independent test Grafana credentials and reuse existing platform
  bootstrap logic without weakening stable clean-main entrypoints.
- Add read-only Rollout/version/digest/GitOps/observability checks and fresh
  test evidence, distinguishing bounded-runtime and explicit operator modes.
- Add offline safety regressions and a complete ordered operator runbook.
- No live AWS qualification, release promotion or prod operation is performed
  by producing/applying this increment's source patch.

## v0.11.8.2.0.1

- Correct the Barman Application-versus-Chart identity in the aws-test
  prerequisite contract and historical AWS revision-boundary validator.
- Derive the external Chart inventory independently from real AWS base
  Application manifests, and improve rendered mismatch diagnostics.
- Preserve the `.8.2.0` offline-only boundary; no cloud or cluster operations.

## v0.11.8.2.0

- Add an offline-only AWS test qualification preview with exact rendered
  resource/revision boundaries and independent Grafana Secret references.
- Define an explicitly loaded four-node capacity profile, positive/negative
  contract checks and the ordered creation/bootstrap/evidence prerequisites.
- Preserve stable test/prod and clean-main entrypoints. No cloud changes,
  release promotion or live qualification are performed by this increment.

## v0.11.8.1.5

- Separate healthy-runtime low-reserve warnings from operational failures;
  retain explicit strict Pod-reserve checks and historical validation.
- Add a read-only, bounded exact-node-group readiness wait after expansion.
- Preserve the info58-65 incident chronology and controlled recovery evidence.
- No changes to capacity targets, credentials, application images, test or prod.

## v0.11.8.1.4

- Budget four aws-dev system nodes and guard expansion against unrelated changes.
- Add per-node Pod-slot preflight and controlled relocation instructions.
- Stabilize Grafana credentials through a create-once independent Secret.
- Record info58-60; keep test/prod, CNI, taints and application images unchanged.

## v0.11.8.1.3

- Separate dev initial creation from existing-cluster endpoint maintenance.
- Fail closed on AWS discovery and Terraform state errors; require intended
  account, empty state, explicit log profile and plan confirmation for creation.
- Document dev/test entrypoints and retain test clean-main guards. No prod changes.
- Add eight mocked runtime regression cases for info57.

All notable changes to this repository are documented in this file.

## v0.11.8.1.2

### Added

- Added an aws-dev-only overlay that aligns all nine same-repository child
  Applications with the current feature revision for pre-merge qualification.
- Added rendered dev/test/prod revision-boundary validation and exact logical
  source plus immutable sync-SHA checks to the aws-dev live qualification.
- Added an explicit restoration gate that returns aws-dev to `main` before the
  feature branch is merged.

### Boundary

- aws-test, aws-prod, external Helm Chart revisions, application code, images,
  infrastructure, and runtime mutation policy are unchanged.

## v0.11.8.1.1

### Fixed

- Made the historical release-orchestration workflow scanner recognize the
  reviewed aws-dev observability qualification workflow only when its v0.11.8.1
  successor contract exists.
- Added strict workflow markers and a negative fixture proving that an
  arbitrary third AWS/EKS workflow remains rejected.

### Boundary

- Validation and documentation only. The workflow, RBAC, checker, AWS runtime,
  application, image, evidence, and main-merge policy are unchanged.

## v0.11.8.1

### Added

- Added an exact-account, region, cluster, Git revision, Chart version, and
  application-version aws-dev observability qualification.
- Added bounded observability read RBAC, private Prometheus/Alertmanager
  port-forward transport, capability-aware evidence writing, and a manual
  trusted-runtime workflow.
- Added explicit `not-deployed` logging/tracing evidence, idle-SLO semantics,
  `waiting-runtime` handling, and offline positive/negative fixtures.

### Boundary

- The qualification does not create or restore AWS infrastructure, generate
  traffic, trigger alerts, mutate a Rollout, synchronize Argo CD, read Secrets,
  execute in Pods, or deploy Loki, Alloy, OTel Collector, or Tempo.

## v0.11.8.0

### Added

- Added the local/aws-dev/aws-test/aws-prod observability qualification matrix,
  explicit capability and whole-environment status vocabularies, and an exact
  environment/revision/release identity lock.
- Added a portable qualification-evidence schema and a fail-closed action
  policy with approval-protected, read-only aws-prod observation.
- Added deterministic positive and negative fixtures for allowed observations,
  production approval, mutation rejection, moving revisions, and false
  qualification of absent runtimes.

### Boundary

- Design and offline contracts only. No AWS environment is created, changed,
  observed, or qualified; no Kubernetes, GitOps, application, image, traffic,
  alert, Rollout, or production runtime state changes.

## v0.11.7.3.1

### Fixed

- Replaced the immediate final Rollout assertion with a five-minute,
  two-second-poll bounded convergence wait locked to the expected application
  version.
- Added timeout diagnostics and deterministic Progressing-to-Healthy and
  version-drift fixtures before final observability checks.

### Boundary

- Validation and documentation only; desired state, image, SLO logic,
  promotion, rollback, AWS runtime, and accepted live evidence are unchanged.

## v0.11.7.3

### Added

- Added one four-phase local SLO/progressive-delivery closure entry point for
  first analysis, human review, second analysis, and final evidence.
- Added explicit human-governed versus fully automated policy boundaries,
  complete operating guidance, retained incident cases, and negative fixtures.
- Added final read-only verification of a Healthy stable Rollout, two
  exact-release AnalysisRuns, SLO foundation, Dashboard, burn-rate rules, and
  actionable alerts.

### Boundary

- Desired state, application image, SLO algorithms, AWS runtime, promotion,
  rollback, and runtime-history retention remain unchanged.

## v0.11.7.2.2

### Fixed

- Required the canary Service selector to resolve Ready Pods with the exact
  expected release ID before the local checker sends traffic.
- Replaced the pre-scrape request burst with bounded traffic across multiple
  Prometheus scrape intervals and moved SLO measurement delay to 90 seconds.
- Added selector/Pod identity diagnostics and stale Endpoint fixtures based on
  the preserved v0.11.7.2.1 failure evidence.

### Boundary

- ServiceMonitor relabeling, application code/image, SLO thresholds, manual
  promotion, rollback ownership, and AWS behavior remain unchanged.

## v0.11.7.2.1

### Fixed

- Repaired unbalanced stable-availability PromQL grouping that Prometheus
  rejected at AnalysisRun execution time.
- Made local SLO acceptance wait for an exact new application version before
  generating stable/canary traffic, removing the 60-second operator race.
- Corrected live deployment guidance to pass the feature branch through
  `TARGET_REVISION` rather than confusing it with `APPLICATION_VERSION`.

### Boundary

- Application code, image, SLO thresholds, human promotion, rollback ownership,
  AWS web-provider behavior, and automatic promotion remain unchanged.

## v0.11.7.2

### Added

- Added release-ID-scoped minimum-sample, availability burn-rate, and latency
  burn-rate metrics to the local Prometheus AnalysisTemplate.
- Added stable-service 30-day availability and latency budget protection and a
  second complete AnalysisRun after the 50% human review pause.
- Added deterministic gate/AnalysisRun fixtures and bounded local live
  acceptance that supplies stable and canary traffic without promoting.

### Boundary

- Application code and appVersion remain unchanged. Analysis failure blocks
  advancement but does not edit Git, create a rollback PR, invoke Rollout undo,
  or change AWS web-provider runtime behavior.

## v0.11.7.1.3

### Fixed

- Replaced the invalid jq `all(... as ...; ...)` expression with deterministic
  construction and subtraction of the 28 required recording-rule names.
- Added exact missing-rule output and separate unsuccessful/malformed
  Prometheus payload diagnostics with executable fixtures.

### Boundary

- Changed validation and documentation only. PrometheusRule manifests, Chart,
  alerts, Dashboard, application image, Rollout, and runtime resources remain
  unchanged; Root advancement and reconciliation are not required.

## v0.11.7.1.2

### Fixed

- Made the SLO live checker expect four Dashboard panels for the foundation and
  six after the burn-rate successor contract exists.
- Added distinct Grafana HTTP, response-body, UID, editability, and expected/
  actual panel-count diagnostics plus deterministic API fixtures.

### Boundary

- Changed validation and documentation only. Dashboard JSON, Chart, recording
  rules, alerts, application image, Rollout, and runtime resources are
  unchanged; Root advancement and reconciliation are not required.

## v0.11.7.1.1

### Fixed

- Replaced cross-template alert list ordering with exact cardinality, unique
  name, and set-equality checks in the historical v0.11.5.1 validator.
- Added deterministic reversed-order, duplicate-name, unexpected-name, and
  missing-name fixtures.

### Boundary

- Changed validation and documentation only. Recording rules, alerts,
  Dashboard, Chart, application image, Rollout, and runtime resources are
  unchanged; reconciliation and live acceptance are not required.

## v0.11.7.1

### Added

- Added availability and latency bad-ratio and normalized burn-rate recording
  rules for 5m, 30m, 1h, 2h, 6h, 1d, and 3d windows.
- Added four paired-window burn-rate alerts: critical fast burn and warning
  slow burn for each SLO, with repository-owned Runbooks.
- Extended the SLO Dashboard and added deterministic formula, boundary, Helm,
  clean-state, and live inventory acceptance.

### Boundary

- Added no application or image change, Rollout gate, automatic rollback,
  external notification provider, AWS runtime change, or live fault injection.

## v0.11.7.0.1

### Fixed

- Added a pre-resource revision gate that requires local HEAD, remote feature
  HEAD, Root, Root child parameter, and all same-repository child Applications
  to use the same immutable commit.
- Added recovery output that reuses the accepted demo-api image while advancing
  the feature Root through `deploy-local-feature-gitops.sh`.
- Documented why `Synced/Healthy`, hard refresh, and direct child sync do not
  advance an immutable Root after a new increment is pushed.

### Boundary

- Changed validation and documentation only. SLO formulas, Dashboard, alerts,
  Rollout, image, Kubernetes desired state, and AWS runtime remain unchanged.

## v0.11.7.0

### Added

- Added explicit 30-day demo-api availability and latency objectives for
  eligible `GET /version` traffic, with bounded release-identity dimensions.
- Added eight recording rules for SLI inputs, SLO ratios, and remaining error
  budgets plus one immutable, recording-rule-only Grafana Dashboard.
- Added a local live acceptance path, machine-readable contract, negative
  mutation tests, and SLO interpretation documentation.

### Boundary

- Added no alert, burn-rate rule, Rollout gate, automatic remediation,
  application code/image change, AWS runtime evidence, or claim of 30-day
  production achievement.

## v0.11.6.2.3.1

### Fixed

- Rejected the historical neutral replay image before live trace-log
  correlation instead of misclassifying its plain access logs as Loki delay.
- Required all ready demo-api replicas to use one runtime image ID and contain
  the accepted structured-logging, tracing, server-entrypoint, and private
  Collector configuration.
- Corrected the v0.11.6.2.3 replay instructions: a fresh unique image built
  from the exact committed feature source is required.

### Boundary

- Changed validation and documentation only. No application source, Helm
  desired state, runtime component, Loki timeout, or AWS runtime was changed.

## v0.11.6.2.3

### Added

- Added one ordered, read-only local minimal tracing closure entrypoint with
  Application, Rollout, private-Service, NetworkPolicy, and Ingress preflight.
- Added two independent real trace-log correlation runs, a machine-readable
  closure contract, negative mutation tests, and a complete operation document.

### Boundaries

- Added no runtime component, application image, AWS tracing state, public OTLP
  endpoint, dynamic Gateway DNS, high availability, or durable trace storage.
- Kept the destructive synthetic Collector replacement drill independently
  accepted and outside the closure entrypoint.

## v0.11.6.2.2

### Added

- Enabled the already accepted demo-api OTLP/HTTP exporter through the local
  App-of-Apps override while retaining the base Chart's disabled default.
- Added real `GET /version` trace acceptance through the private Collector and
  Tempo runtime, including Loki JSON-log correlation by the same W3C trace ID.
- Provisioned one private, non-default, non-editable Grafana Tempo data source
  and one Loki `TraceID` derived field, with bounded Grafana egress to Tempo.
- Added a machine-readable contract, focused offline validation, live Grafana
  data-source health checks, and consecutive two-run acceptance instructions.

### Boundary

- This increment reuses the v0.11.6.2.0 tracing-capable application image and
  changes no application code. Trace and span identifiers remain unindexed
  JSON fields. PostgreSQL live tracing, AWS runtime changes, service graphs,
  span metrics, sampling, exemplars, object storage, high availability, public
  OTLP ingress, and tracing dashboards remain deferred.

## v0.11.6.2.1.1

### Fixed

- Corrected the synthetic OTLP/JSON acceptance payload to encode `traceId` and
  `spanId` as 32- and 16-character hexadecimal strings instead of Base64.
- Added strict rejection of malformed and all-zero synthetic identifiers and a
  dedicated payload generator with deterministic protocol-shape tests.
- Preserved the Collector HTTP 400 status and a bounded response body in live
  failure output, and made Tempo and Collector diagnostics explicit rather
  than relying on one shared label selector.

### Boundary

- This repair changes acceptance tooling and documentation only. Collector,
  Tempo, demo-api, Helm, Kubernetes resources, images, configuration, storage,
  and network policy remain unchanged; no reconciliation or image rebuild is
  required.

## v0.11.6.2.1

### Added

- Added one private single-replica OpenTelemetry Collector Gateway with an
  OTLP/HTTP traces-only pipeline, bounded queue/retry behavior, memory limiting,
  batching, strict resources, and no Kubernetes RBAC requirement.
- Added a repository-owned minimal Tempo Chart pinned to Tempo 3.0.3, one
  monolithic replica, bounded local filesystem storage, 24-hour retention,
  private query/ingest Services, and runtime NetworkPolicies.
- Added synthetic Collector-to-Tempo live acceptance, Tempo query validation,
  Collector Pod replacement history validation, focused offline validation,
  and a machine-readable runtime contract.

### Boundary

- demo-api export remains disabled. No application code, application image,
  logging runtime, Grafana data source, database, AWS state, workflow, public
  endpoint, external credential, sampling processor, or production durability
  claim is added. Local platform reconciliation is required; image rebuilding
  is not.
- The deprecated external Tempo Chart is explicitly rejected. The local
  repository-owned Chart contains only the minimal Tempo runtime resources.

## v0.11.6.2.0

### Added

- Added explicitly enabled OpenTelemetry SDK initialization, W3C Trace Context
  extraction, one bounded HTTP SERVER span, controlled PostgreSQL CLIENT spans,
  and valid-context `trace_id`/`span_id` JSON log correlation.
- Added exact OpenTelemetry 1.44.0 dependency pins, one shared log/trace release
  identity source, 29 application unit tests, a machine-readable tracing
  contract, focused offline validation, and a disabled-state live checker.
- Added identical disabled-by-default OTLP/HTTP configuration to the Deployment
  and Rollout paths and advanced the demo-api Chart to `0.7.0` with application
  version `0.5.0`.

### Security

- Restricted spans to method, route template, status, database system, and one
  allowlisted operation name. Raw URL/query/body/header/SQL/parameter/database
  URL and exception text capture remains forbidden.
- Suppressed liveness, readiness, and metrics spans, suppressed the
  readiness database child span, rejected baggage and credential-bearing OTLP
  endpoints, and left sampling outside application configuration.

### Boundary

- OTLP export remains disabled and creates no exporter or background processor.
  No Collector, Tempo, Grafana trace data source, Operator instrumentation,
  Kubernetes resource, Loki/Alloy/Grafana value, AWS state, workflow, public
  endpoint, external credential, or production automation is added. A unique
  demo-api image rebuild and local reconciliation are required.

## v0.11.6.1.3

### Added

- Added one local structured-logging closure entrypoint that runs the normal
  platform validation, Pod-log runtime acceptance, Events/Grafana acceptance,
  and final Application/PVC/residual-resource assertions in a fixed order.
- Added stage-scoped failure diagnostics, a machine-readable closure contract,
  an offline validator, two-run live acceptance instructions, and negative
  mutations for skipped repetition, Event residue, destructive storage
  recovery, runtime expansion, image rebuilding, and early tracing.
- Made the v0.11.6.1.2.2 historical validator successor-aware so the accepted
  repair remains replayable after the active checkpoint advances to closure.

### Changed

- Made successful Events acceptance delete both temporary Kubernetes Event
  objects strictly before reporting success, while retaining best-effort trap
  cleanup on abnormal exit.
- Added post-cleanup queries proving that deleting temporary Kubernetes source
  objects does not remove or duplicate the already accepted Loki history.

### Boundary

- This closure changes no Kubernetes resource, application code or image,
  Chart or application version, Loki/Alloy/Grafana value, PVC, StorageClass,
  RBAC, NetworkPolicy, indexed label, AWS state, workflow, public endpoint,
  credential, production automation, or tracing runtime. No reconciliation or
  image rebuild is required.

## v0.11.6.1.2.2

### Fixed

- Replaced the nine-digit GNU `date %N` value used for
  `events.k8s.io/v1 Event.eventTime` with an explicit UTC Python timestamp
  containing exactly six fractional digits. The local API server can now
  decode the value as Kubernetes `MicroTime`.
- Kept temporary Event cleanup registration after successful API creation, so
  an API validation failure cannot claim or attempt to clean a resource that
  was never created.

### Added

- Added a repair contract, incident record, focused validator, predecessor
  successor coverage, and negative mutations for nanosecond precision, missing
  UTC normalization, early cleanup registration, and runtime overstatement.

### Boundary

- This repair changes only the local Events live-acceptance timestamp and its
  offline evidence. It changes no Kubernetes resource, local platform Chart,
  application image, Events collector, PVC, Alloy/Loki value, Grafana data
  source, RBAC, NetworkPolicy, indexed label, AWS state, workflow, credential,
  public endpoint, production automation, or tracing runtime.

## v0.11.6.1.2.1

### Fixed

- Moved `logging-alloy-events` from sync wave `9` to wave `8`, matching its
  Root-owned position claim so the local `WaitForFirstConsumer` StorageClass
  can bind only after the Event collector Pod is schedulable without blocking
  that consumer Application from being created.
- Replaced substring-based historical logging Application cardinality checks
  with exact rendered Application-name counting. `logging-alloy-events` no
  longer causes the predecessor `logging-alloy` check to fail.
- Bounded feature and baseline-restoration Argo CD sync commands with
  `WAIT_TIMEOUT_SECONDS` and emit Application diagnostics when a sync fails.

### Added

- Added a version-specific troubleshooting record for the PVC/consumer sync
  deadlock, misleading Argo CD permission response, safe operation termination,
  non-destructive recovery, verification commands, and prevention invariant.
- Added a repair contract, focused validator, successor coverage, and negative
  mutations for cross-wave storage, unbounded sync, substring cardinality, and
  troubleshooting omission regressions.

### Boundary

- This repair changes no external Chart or application image, Alloy or Loki
  runtime values, PVC size, StorageClass, RBAC, NetworkPolicy, Event labels,
  Grafana data source, AWS state, public endpoint, credential, production
  automation, or tracing runtime.

## v0.11.6.1.2

### Added

- Added a pinned `logging-alloy-events` Argo CD Application that deploys Alloy
  `1.18.0` as a one-replica Deployment and watches Kubernetes Events through
  the API without duplicating collection across node-local Pod-log collectors.
- Added a 256Mi ReadWriteOnce positions claim so routine Event-collector Pod
  replacement does not replay the Kubernetes Event TTL window.
- Added a non-default, non-editable Grafana Loki data source with server-side
  proxy access to the private Loki gateway.
- Added exact Event RBAC, six-label cardinality, NetworkPolicy, Grafana health,
  Event query, collector restart, replay-rejection, and resumed-collection
  acceptance checks.

### Changed

- Advanced the local platform Chart to `0.6.0` and application version to
  `v0.11.6.1.2`.
- Allowed the cluster-only Grafana Deployment to query the Loki gateway on
  internal port `8080`.

### Boundary

- This increment changes no demo-api code or image, Pod-log Alloy values, Loki
  values, Prometheus data source, Dashboard, alert rule, AWS state, external
  credential, public endpoint, production automation, or tracing runtime.

## v0.11.6.1.1.5

### Fixed

- Restricted local Kubernetes API Pod-log readers to `startup-apps`, preventing
  dense one-node kind clusters from exhausting fsnotify watchers while keeping
  node-local discovery, non-root execution, and host-mount-free collection.
- Matched Pod name and UID from Loki-returned structured metadata while keeping
  release and HTTP identity checks against the original demo-api JSON record.
- Replaced query-label inventory checks with the Loki Series API so structured
  metadata and automatic detected level cannot be misclassified as indexed
  stream labels.
- Added content-filtered demo-api queries and a bounded guard that rejects new
  `failed to create fsnotify watcher: too many open files` entries.

### Added

- Added a repair contract, design record, focused validator, and negative
  mutations for cluster-wide reader restoration, system-namespace expansion,
  mutable host sysctl dependency, label-API inventory, fsnotify acceptance, and
  premature live-success claims.

### Boundary

- This repair keeps local platform `0.5.0` / `v0.11.6.1.1`, Loki
  `18.11.3` / `3.7.6`, Alloy `1.11.0` / `1.18.0`, their security and network
  boundaries, and the six indexed-label contract. It changes no Loki value,
  demo-api code or image, Grafana data source, Event collection, tracing, AWS
  state, host sysctl, public endpoint, credential, or production automation.

## v0.11.6.1.1.2

### Fixed

- Pinned the Alloy process to the image-defined non-root UID/GID `473` and
  assigned Pod `fsGroup` `473`, allowing Kubernetes to enforce
  `runAsNonRoot` without treating the image as root.
- Disabled the Loki rules sidecar because this local logging increment does
  not deploy ruler ConfigMaps or Secrets. The Loki Pod no longer depends on a
  sidecar that cannot authenticate while ServiceAccount token automounting is
  intentionally disabled.

### Added

- Added source, rendered-manifest, and live-cluster checks for Alloy UID/GID,
  Loki single-container topology, token non-automount, memberlist discovery,
  and bounded Loki restart stability.
- Added a repair contract, design record, focused validator, and negative
  mutations for root execution, rules-sidecar re-enablement, token mounting,
  memberlist topology changes, and premature runtime-success claims.

### Boundary

- This repair keeps local platform `0.5.0` / `v0.11.6.1.1`, Loki
  `18.11.3` / `3.7.6`, Alloy `1.11.0` / `1.18.0`, the existing memberlist
  topology, least-privilege Alloy RBAC, and the six-label index contract. It
  changes no demo-api code or image, Grafana data source, Event collection,
  tracing, AWS state, public endpoint, credential, or production automation.

## v0.11.6.1.1.1

### Fixed

- Replaced the explicitly empty Alloy `rbac.clusterRules` value with a second
  non-empty least-privilege rule list so the pinned Alloy Chart can render a
  valid ClusterRole.
- Made the v0.11.2 and v0.11.3.2 historical validators accept the authoritative
  v0.11.6.1.0 demo-api Chart `0.6.0` / application version `0.4.0` successor
  while preserving their original pre-successor expectations.
- Made the v0.11.4.0.1 fake Helm fixture include the two pinned logging
  Applications only when the v0.11.6.1.1 successor contract exists.

### Added

- Added source and rendered-manifest regression checks that reject empty Alloy
  RBAC lists and require exactly `namespaces`, `pods`, and `pods/log`.
- Added a repair contract, design record, focused validator, and negative
  mutations for RBAC expansion, successor downgrade, and runtime-evidence
  overstatement.

### Boundary

- This repair keeps local platform `0.5.0` / `v0.11.6.1.1`, Loki
  `18.11.3` / `3.7.6`, Alloy `1.11.0` / `1.18.0`, and demo-api
  `0.6.0` / `0.4.0`. It changes no application code or image, Loki value,
  Alloy collection pipeline, label contract, Grafana data source, Event
  collection, tracing, AWS state, public endpoint, credential, or production
  automation.

## v0.11.6.1.1

### Added

- Added pinned local `logging-loki` and `logging-alloy` Argo CD Applications
  after the existing observability stack.
- Added one private Loki Monolithic replica with TSDB v13, filesystem storage,
  a 2 GiB disposable volume, 24-hour retention, bounded resources, and
  cluster-only NetworkPolicy.
- Added an Alloy DaemonSet that discovers same-node Pods, reads logs through
  the Kubernetes API, preserves malformed/non-JSON lines, extracts severity,
  and sends logs only to the private Loki gateway.
- Added exact indexed-label and structured-metadata contracts plus offline and
  local live validators, including a demo-api Pod replacement persistence
  check.

### Changed

- Advanced the local platform Chart to `0.5.0` and application version to
  `v0.11.6.1.1`.
- Made the general local validator wait for both logging Applications and all
  logging workloads, avoiding transient first-run readiness failures.

### Boundary

- This increment changes no demo-api source or image, monitoring or
  Alertmanager configuration, Grafana data source, Kubernetes Event stream,
  tracing component, AWS state, public endpoint, external credential,
  production automation, AI infrastructure, AIOps, or OpenClaw integration.

## v0.11.6.1.0

### Added

- Added one-line JSON process logging for demo-api with the required service,
  environment, release, source-commit, and image-digest identity fields.
- Added bounded HTTP completion records, normalized route templates, status-
  based severity, probe-noise suppression, and sensitive request-data tests.
- Projected the canonical release ID, source commit, and image digest from Pod
  annotations into both Deployment and Rollout containers through the
  Kubernetes Downward API.
- Added offline and local live validators for JSON syntax, release-identity
  parity, quiet successful probes, failed-request visibility, and raw path and
  query rejection.

### Changed

- Changed the demo-api entrypoint to install one JSON formatter for application
  and Uvicorn process logs while disabling the duplicate Uvicorn access stream.
- Advanced the demo-api Chart to `0.6.0` and application version to `0.4.0`.

### Boundary

- This first v0.11.6.1 subincrement requires a new demo-api image and local
  application redeployment. It adds no Loki, Alloy, Kubernetes Event
  collection, Grafana data source, monitoring redeployment, tracing, AWS
  mutation, public endpoint, external credential, AI infrastructure, AIOps,
  or OpenClaw integration.

## v0.11.6.0

### Added

- Added the per-environment centralized logging contract: demo-api JSON Lines,
  Alloy Pod-log and Kubernetes Event collection, environment-local Loki, and
  bounded retention and storage profiles.
- Added the minimal vendor-neutral tracing contract: W3C Trace Context,
  OpenTelemetry APIs, OTLP through an upstream Collector, collector-owned
  sampling, and an environment-local Tempo backend.
- Added exact log fields, forbidden sensitive data, bounded Loki labels,
  metric-log-trace-release correlation, the v0.11.6.1 through v0.11.6.4
  implementation sequence, and negative boundary mutations.
- Recorded the repaired v0.11.5 alert lifecycle as accepted locally.

### Boundary

- This design-only increment adds no application code, image, Helm dependency,
  Kubernetes resource, logging or tracing runtime, public endpoint, external
  credential, AWS mutation, production automation, AI infrastructure, AIOps,
  or OpenClaw integration. Runtime implementation begins in v0.11.6.1.

## v0.11.5.2.0.3

### Fixed

- Separated Kubernetes PrometheusRule deletion from asynchronous Prometheus
  rule-inventory convergence before the exact nine-alert assertion.
- Made the normal final Kubernetes cleanup strict so deletion failures are no
  longer hidden by best-effort error suppression.

### Added

- Added a bounded wait after every phase deletion and before final baseline
  validation for both temporary alert definitions to disappear from
  `/api/v1/rules`.
- Added timeout diagnostics and negative mutation coverage for a premature
  formal-baseline check and best-effort final cleanup.

### Boundary

- This repair changes only the guarded local drill, contracts, and
  documentation. It changes no Kubernetes desired state, monitoring Chart,
  Alertmanager configuration, permanent rule, formal alert, webhook sink,
  application image, AWS resource, or production automation and requires no
  monitoring redeployment or image rebuild.

## v0.11.5.2.0.2

### Fixed

- Replaced delete-before-resolved lifecycle handling with an explicit
  `vector(1)` to empty-vector `vector(0) == 1` transition that retains the same
  temporary rule, alert name, and labels until resolved delivery is observed.
- Required Prometheus clearing before resolved-webhook evidence and delayed
  PrometheusRule deletion until each notifying phase completes.

### Added

- Added preflight and final global checks that reject active `drill="true"`
  alerts from the current or an earlier failed run.
- Added exact lifecycle-order validation and negative mutations for premature
  rule deletion and numeric-zero-only expressions.

### Boundary

- This repair changes only the guarded local drill, contracts, and
  documentation. It changes no Kubernetes desired state, monitoring Chart,
  Alertmanager configuration, route, receiver, NetworkPolicy, webhook sink,
  formal alert, application image, AWS resource, or production automation and
  requires no monitoring redeployment or image rebuild.

## v0.11.5.2.0.1

### Fixed

- Replaced the live plaintext webhook URL assertion with an exact two-line
  `<secret>` assertion matching Alertmanager's `/api/v2/status`
  representation.
- Kept exact internal plaintext URL checks in desired-state and literal
  fixtures instead of weakening the security boundary.

### Added

- Added exact redacted, missing-redaction, and mixed plaintext/redacted runtime
  fixtures plus the observed first-run evidence contract.
- Distinguished Alertmanager global provider API defaults from configured
  external receiver blocks.

### Boundary

- This repair changes only the Alertmanager acceptance parser, contracts, and
  documentation. It changes no Kubernetes desired state, Helm Chart,
  Alertmanager route or receiver, NetworkPolicy, formal alert, webhook sink,
  drill phase, application image, AWS resource, or production automation and
  requires no monitoring redeployment.

## v0.11.5.2.0

### Added

- Added narrowly matched critical and warning drill routes that continue into
  the existing severity routes and deliver firing and resolved payloads only
  to a temporary in-cluster webhook sink.
- Added a guarded local drill covering warning and critical lifecycles,
  positive critical-over-warning inhibition, unequal-component isolation, and
  zero-residual cleanup.
- Added a bounded Python webhook fixture, exact offline contract, negative
  public-URL tests, live acceptance documentation, and successor-aware
  historical validators.

### Changed

- Added Alertmanager TCP 8080 egress only to the labeled drill sink Pod in the
  `observability` Namespace.
- Advanced the local platform Chart from `0.4.0` to `0.4.1` with application
  version `v0.11.5.2.0`.
- Recorded v0.11.5.1.1.1 as accepted through the repaired local live path.

### Boundary

- This increment changes no formal alert, threshold, duration, Dashboard,
  recording rule, monitor, application image, Rollout gate, AWS resource,
  release automation, SLO, logging, or tracing behavior. It configures no
  public webhook, external provider, notification credential, Silence, or
  real workload failure.

## v0.11.5.1.1.1

### Fixed

- Corrected the target-count live preflight to query the Chart-declared
  `operator-diagnostic-recording-rules` resource instead of the nonexistent
  `operator-recording-rules` name.
- Replaced stale-image reuse guidance with the required unique current-source
  build and kind-load transition after neutral feature-baseline restoration.

### Added

- Added a focused contract and mutation check that bind the live script's
  default resource identity to PrometheusRule template metadata.
- Recorded the observed historical metric mismatch and the subsequent direct
  confirmation of populated HTTP and PostgreSQL dependency metrics.

### Boundary

- This repair changes one live validation lookup plus contracts and
  documentation. It changes no Kubernetes desired state, Chart version,
  recording rule, alert, Dashboard, monitor, Alertmanager configuration,
  application source, image content, AWS resource, or production automation.

## v0.11.5.1.1

### Fixed

- Replaced the target-down filter comparison with `up == bool 0`, so each up
  target contributes zero and each down target contributes one before the
  namespace/job aggregation.
- Preserved absent target groups as no-data instead of inventing a zero series.

### Added

- Added `PrometheusTargetDown` as the ninth repository-owned actionable alert,
  with critical severity, a 10-minute duration, stable routing labels, and one
  reviewed English Runbook.
- Added offline all-up, one-down, two-down, absent, and filter-regression
  checks plus a live recorded-versus-direct Prometheus query cross-check.

### Changed

- Advanced the observability views Chart from `0.4.0` to `0.4.1` with
  application version `v0.11.5.1.1`.
- Updated historical v0.11.4 and v0.11.5 validators for the semantic-repair
  successor while preserving the accepted eight-alert v0.11.5.1 contract.
- Recorded v0.11.5.1 as accepted through local live validation.

### Boundary

- This repair changes one recording-rule expression and adds one alert and
  Runbook. It changes no Dashboard, monitor, monitoring stack, Alertmanager
  route, external receiver, credential, image, Rollout gate, SLO, AWS resource,
  or production automation and does not deliberately fail a real target.

## v0.11.5.1

### Added

- Added eight repository-owned actionable alerts covering demo-api HTTP and
  dependency reliability, Argo Rollouts, Argo CD Application health,
  Kubernetes Deployment availability, and AWS-profile CloudNativePG
  collection health.
- Added one English, version-controlled Runbook per alert with read-only first
  response, release correlation, recovery verification, and preserved
  production approval boundaries.
- Added exact offline and local/AWS live acceptance for inventory, metadata,
  rule health, stable inhibition labels, Runbook links, and a clean inactive
  baseline.

### Changed

- Advanced the repository-owned observability views Chart from `0.3.1` to
  `0.4.0` with application version `v0.11.5.1`.
- Made historical v0.11.4 and v0.11.5.0 validators aware of the alert-rule
  Chart successor without weakening their accepted contracts.
- Recorded v0.11.5.0.1 as accepted through the direct local live rerun.

### Boundary

- This increment adds no default rule set, external receiver, notification
  credential, Dashboard, recording rule, monitor, application image,
  Alertmanager route, SLO, Rollout gate, AWS mutation, or production
  automation. Firing, routing, inhibition, resolution, and notification-path
  drills remain v0.11.5.2 work.

## v0.11.5.0.1

### Fixed

- Made live Alertmanager severity-matcher validation insensitive to optional
  whitespace around the equals sign in the canonical `/api/v2/status` output.
- Required exactly two critical and two warning matchers so both severity
  routes and the critical-over-warning inhibition contract remain enforced.
- Added observed matcher-line diagnostics for missing or duplicated matchers.

### Added

- Added shared offline/live configuration validation plus spaced, canonical
  compact, and incomplete matcher regression fixtures.

### Boundary

- This repair changes validation, contracts, and documentation only. It
  changes no Alertmanager runtime configuration, Kubernetes resource, route,
  receiver, alert rule, image, storage, AWS desired state, or production
  automation and requires no GitOps redeployment.

## v0.11.5.0

### Added

- Enabled one environment-local Alertmanager for local, aws-dev, aws-test, and
  aws-prod through the pinned kube-prometheus-stack `88.5.0` release.
- Added exact environment, cluster, component, and alert-family grouping;
  critical and warning observation routes; and bounded critical-over-warning
  inhibition.
- Added private ClusterIP exposure, least-privilege NetworkPolicy, bounded
  resources, token-automount disablement, local ephemeral storage, and
  dedicated encrypted AWS gp3 persistence profiles.
- Added a focused offline contract and a live check for Alertmanager readiness,
  active configuration, Prometheus endpoint discovery, and self-monitoring.

### Changed

- Advanced the local platform Chart from `0.3.0` to `0.4.0` with application
  version `v0.11.5.0`.
- Made historical metrics, feature-rendering, Grafana, and controller-metric
  validators aware of the Alertmanager successor without changing their
  accepted historical contracts.
- Closed v0.11.4 after the accepted v0.11.4.2.2 clean local replay.

### Boundary

- The observation receivers contain no external notification integration.
  This increment adds no alert rule, Runbook, Dashboard, recording rule,
  application telemetry, central Alertmanager, HA claim, SLO, Rollout gate,
  AWS mutation, or production automation.

## v0.11.4.2.2

### Fixed

- Rejected discovered demo-api Prometheus targets unless their numeric `up`
  value is positive, instead of treating a non-empty zero result as healthy.
- Added active-target `health`, scrape URL, `lastError`, and last-scrape
  diagnostics for application telemetry failures.
- Centralized bounded demo-api traffic and direct source-metric preflight so a
  neutral-baseline or stale image fails before downstream recording rules.
- Required a fresh local image tag and exact feature redeployment between
  neutral-baseline restoration and clean-replay acceptance.

### Boundary

- This repair changes validation scripts, contracts, and documentation only.
  It changes no Kubernetes resource, Dashboard, recording rule,
  ServiceMonitor, image, Canary behavior, AWS desired state, or production
  automation.

## v0.11.4.2.1

### Added

- Added an immutable Capacity and Resource Efficiency Grafana Dashboard that
  consumes all twenty recording rules accepted in v0.11.4.2.0.
- Added namespace filtering, resource-interpretation descriptions, request
  coverage, and reservation-proxy panels without raw metric queries.
- Added profile-aware live acceptance for the fifth Dashboard ConfigMap,
  representative finite rule data, fixed Dashboard identities, panel counts,
  immutability, tags, and variable contract.

### Changed

- Advanced the repository-owned observability views Chart from `0.3.0` to
  `0.3.1` with application version `v0.11.4.2.1`.
- Made historical v0.11.4 rule and Dashboard validators aware of the Capacity
  Dashboard successor without weakening their accepted contracts.

### Boundary

- This increment adds one Dashboard and Chart metadata only. It adds no
  recording rule, monitor, exporter, alert, autoscaling action, Karpenter
  policy, Kubecost, AWS Billing integration, currency-cost claim, Canary
  change, or production automation.

## v0.11.4.2.0

### Added

- Added twenty capacity and resource-efficiency recording rules for cluster
  allocatable resources, active workload requests and limits, Pod capacity,
  namespace usage-to-request ratios, and request coverage.
- Added profile-aware live discovery for existing kube-state-metrics and
  kubelet/cAdvisor sources, rule health, finite ratios, and `startup-apps`
  request-coverage results.
- Added an offline contract and focused validator for source ownership, active
  workload semantics, bounded zero anchors, and scope boundaries.

### Changed

- Advanced the repository-owned observability views Chart from `0.2.2` to
  `0.3.0` with application version `v0.11.4.2.0`.
- Made historical v0.11.4 rule and Dashboard validators aware of the capacity
  signal successor without changing their accepted rule or Dashboard sets.

### Boundary

- This increment reuses existing core monitoring targets. It adds no
  Dashboard, monitor, exporter, alert, autoscaling action, Karpenter policy,
  Kubecost, AWS Billing integration, currency-cost claim, Canary change, or
  production automation.

## v0.11.4.1.1

### Added

- Added immutable Delivery, Data, and Platform Grafana Dashboards backed only
  by the twenty-one recording rules accepted in v0.11.4.1.0.
- Added profile-aware live acceptance for Dashboard provisioning, Grafana API
  immutability, and required Delivery, Data, and Platform rule results.
- Added an offline contract and focused validator for Dashboard identity,
  panel inventory, query ownership, conditional CloudNativePG no-data, and
  scope boundaries.

### Changed

- Advanced the repository-owned observability views Chart from `0.2.1` to
  `0.2.2` with application version `v0.11.4.1.1`.
- Made historical v0.11.4.0, v0.11.4.1.0, and v0.11.4.1.0.2 validators aware
  of the Dashboard successor without weakening their original contracts.

### Boundary

- This increment changes Dashboard JSON and Chart metadata only. It adds no
  recording rule, monitor, alert, log or trace backend, SLO, capacity or cost
  panel, Grafana exposure or persistence, AWS desired state, Canary behavior,
  or production automation.

## v0.11.4.1.0.2

### Fixed

- Anchored the HTTP error-rate zero fill to existing request-rate label sets so
  successful traffic without a `5xx` series produces a success ratio of one
  while a completely missing request stream remains no-data.
- Applied the same bounded behavior to dependency success ratios so an
  observed dependency with failures but no success series produces zero rather
  than disappearing.
- Replaced the generic ratio no-series hint with source-rule cardinality
  diagnostics that distinguish warm-up from an expression mismatch.

### Changed

- Advanced the repository-owned observability views Chart from `0.2.0` to
  `0.2.1` with application version `v0.11.4.1.0.2`.
- Made historical v0.11.4.0 and v0.11.4.1.0 validators aware of the accepted
  Chart successor without changing their historical contracts.

### Boundary

- This repair changes two recording-rule expressions and their acceptance
  diagnostics only. It adds no rule name, Dashboard, alert, global
  `or vector(0)` fallback, component upgrade, Grafana Deployment setting,
  ReplicaSet cleanup, AWS state, or production automation.

## v0.11.4.1.0.1

### Fixed

- Changed labeled Pod validation to retry discovery before waiting for Ready,
  and preserved the final Kubernetes API error instead of reporting every
  transient list failure as an empty selector result.
- Replaced the invalid named ConfigMap plus label-selector query in the local
  observability acceptance script with an exact-name lookup followed by an
  independent `grafana_dashboard=1` label assertion.

### Added

- Added focused static and behavioral regression coverage for transient Pod
  discovery errors, empty first results, persistent API errors, missing Pods,
  and the Grafana Dashboard ConfigMap lookup contract.
- Documented the distinction between the pre-merge feature baseline and the
  post-merge stable HEAD baseline.

### Boundary

- This repair changes validation scripts, contracts, and documentation only.
  It changes no Kubernetes resource, Helm Chart, component version, metric,
  recording rule, Dashboard, alert, AWS desired state, or production
  automation.

## v0.11.4.1.0

### Added

- Added repository-owned ServiceMonitors for Argo CD and Argo Rollouts plus
  AWS-only PodMonitors for the CloudNativePG operator and PostgreSQL instances.
- Added twenty-one Delivery, Data, and Platform diagnostic recording rules and
  a profile-aware live discovery check for controller versions, targets, raw
  metrics, loaded rules, and required query results.
- Added an exact machine-readable component and metric contract, focused
  offline validation, negative boundary mutations, and a local/AWS acceptance
  Runbook.

### Changed

- Added live Argo CD semantic-version observation without changing its
  existing installation or Kubernetes-compatibility boundary.
- Advanced Argo Rollouts from Chart `2.41.0` to `2.41.1`, enabled its metrics
  Service, and pinned the resulting controller application version to
  `v1.9.1`.
- Advanced the local platform Chart to `0.3.0` and the repository-owned
  observability views Chart to `0.2.0`.

### Boundary

- This increment adds no Dashboard, alert, Alertmanager routing, SLO, burn
  rate, log backend, trace backend, cloud billing integration, Canary step, or
  production automation. Delivery, Data, and Platform Dashboards continue in
  v0.11.4.1.1.

## v0.11.4.0.1

### Fixed

- Made the v0.11.3.4 Helm-render regression successor-aware so the accepted
  local child set includes `observability-views` when the v0.11.4.0 contract is
  present.
- Verified `observability-views` uses `HEAD` in the stable render and the same
  resolved full SHA as other same-repository children in the feature render.

### Added

- Added a deterministic fake-Helm regression that executes the previously
  skipped branch even when Helm is unavailable in the package producer.

### Boundary

- This repair changes validation, contracts, and documentation only. It changes
  no runtime resource, Grafana setting, Dashboard, recording rule, Argo CD
  Application, AWS desired state, or production automation.

## v0.11.4.0

### Added

- Enabled private, resource-bounded Grafana profiles for local and AWS without
  public ingress or persistent UI state.
- Added the repository-owned `observability-views` Helm Chart and Argo CD
  Applications with unified local feature-revision ownership.
- Added nine bounded demo-api recording rules and one immutable service overview
  Dashboard provisioned from Git.
- Added focused offline validation, negative boundary cases, and an executable
  local Grafana and recording-rule acceptance check.

### Changed

- Advanced the local App-of-Apps Chart to `0.2.0` and extended feature
  deployment, baseline restoration, and active-revision validation to the new
  same-repository observability Application.
- Made the v0.11.1 and v0.11.3.4 historical validators successor-aware without
  rewriting their historical contracts.

### Boundary

- This increment adds no Alertmanager, alert rule, centralized log backend,
  trace backend, SLO target, burn-rate policy, Kubecost deployment, billing
  integration, Rollout gate, AWS runtime mutation, or production automation.

## v0.11.3.6

### Fixed

- Updated namespace guardrail validation to inspect the Helm Application
  template and its stable Git values instead of the removed raw local YAML.
- Rejected reintroduction of the legacy raw namespace guardrail Application.
- Changed the local admission-policy boundary scan from shallow to recursive so
  forbidden strict-digest Applications cannot hide under Helm templates.

### Added

- Added dynamic negative fixtures for both migration failure modes plus a
  machine-readable contract and focused validation Runbook.

### Boundary

- This repair changes validation and documentation only. It changes no
  namespace resource, admission policy, platform Chart, application, telemetry,
  Canary behavior, AWS desired state, or production automation.

## v0.11.3.5

### Fixed

- Prevented a Helm-shaped Root Application from targeting an older remote
  revision that does not contain `clusters/local/platform/Chart.yaml`.
- Added a remote revision content preflight before any Kubernetes access, so a
  pre-merge `HEAD` mismatch fails without changing the live Root Application.
- Split restoration into an immutable pre-merge feature baseline and a
  post-merge HEAD baseline backed by one shared declarative implementation.
- Blocked restoration sync while an Application has `ComparisonError`; child
  prune indicators produced by failed manifest generation remain non-actions.

### Added

- Added positive and negative fake-client regression cases, a machine-readable
  incident contract, and an exact recovery and acceptance Runbook.

### Boundary

- This repair changes no platform or demo-api Chart, image, telemetry,
  Prometheus gate, Canary strategy, external Chart version, AWS state, release
  orchestrator, or production automation.

## v0.11.3.4

### Changed

- Converted the local platform App-of-Apps directory into a lightweight Helm
  Chart with one `git.targetRevision` value for same-repository Applications
  and independently pinned external Chart versions.
- Resolved the operator-supplied `TARGET_REVISION` once to a full remote commit
  SHA, required the local checkout to match it, and supplied that immutable SHA
  to the Root, namespace guardrails, and demo-api.
- Moved the exact four local demo-api image parameters under Root ownership so
  feature deployment and HEAD restoration no longer directly `set` or `unset`
  child Application fields.
- Replaced the bounded Root `OutOfSync` feature state with declarative Root
  `Synced` ownership; Root resync is now safe during feature validation.

### Added

- Added stable/feature Root rendering tests, remote-branch resolution tests,
  optional Helm lint/render assertions, a machine-readable contract, and a
  clean replay Runbook.

### Boundary

- The demo-api Chart, image, telemetry, Prometheus gate, Canary strategy,
  external Chart versions, AWS state, and production automation are unchanged.

## v0.11.3.3

### Fixed

- Added exact, bounded retry when Argo CD rejects a `sync`, `set`, or `unset`
  mutation with `another operation is already in progress` after the
  Application custom resource already appears idle.
- Unified feature deployment and HEAD restoration on one operation
  serialization helper, increased stable idle observations to three, and
  added Application diagnostics when the five-attempt bound is exhausted.
- Kept permission, validation, repository, and all non-busy errors as immediate
  failures instead of hiding them behind retries.

### Added

- Added executable transient-busy, permanent-busy, non-busy-error, and invalid
  configuration regression cases plus a machine-readable incident contract and
  clean live-replay acceptance Runbook.

### Boundary

- This patch changes no Chart, image, telemetry, Prometheus gate, Canary steps,
  AWS state, production automation, or active tracked GitOps revision.

## v0.11.3.2

### Fixed

- Added a configurable 60-second metric `initialDelay` so Prometheus Operator
  discovery and the first Canary scrape can converge before analysis begins.
- Replaced unsafe direct `result[0]` access with a fail-closed vector-length
  guard. An empty Prometheus result now becomes a failed measurement instead of
  `reflect: slice index out of range`, and it is never accepted as success.
- Advanced the demo-api Chart to `0.5.1` and recorded the revision 22 cold-start
  AnalysisRun failure that exposed the defect.

### Added

- Added a machine-readable no-data policy, positive and negative validation,
  operator recovery guidance, and a clean-replay acceptance boundary.

### Boundary

- The Prometheus query, metric schema, ServiceMonitor, Canary step sequence,
  manual Promotion, AWS declarations, and production automation are unchanged.

## v0.11.3.1

### Fixed

- Removed the Root create/apply auto-sync race by rendering manual feature and
  restoration modes without `spec.syncPolicy.automated` before Kubernetes sees
  the Application.
- Serialized Argo CD operations, paused child automation during overrides, and
  explicitly removed stale live Helm parameters that could mask the
  Git-declared AnalysisTemplate Prometheus address.
- Corrected the Rollout retry example to include the required `rollout`
  resource type and documented that the observed recovery occurred through
  revision 15 reconciliation, not the rejected retry command.

### Added

- Added an exact four-parameter feature allowlist, empty-parameter restoration
  assertion, negative recovery validation, incident contract, and a dependency
  map from Root GitOps through Prometheus-backed Canary analysis.

### Boundary

- This patch changes no application telemetry, monitoring stack, Canary steps,
  AWS state, production automation, or stable tracked `HEAD` revision.

## v0.11.3

### Added

- Added a parameterized local feature-revision GitOps workflow that sets the
  Root to manual sync, synchronizes it once, and then pins same-repository child
  Applications to the same requested revision.
- Added local image injection plus exact revision, Chart, ServiceMonitor and
  AnalysisTemplate Prometheus-address assertions without masking telemetry
  values from Git.
- Added declarative restoration of the local `HEAD` baseline, automated Root
  sync and self-heal, together with a machine-readable contract, positive and
  negative validation, and an operator Runbook.

### Changed

- Added `TARGET_REVISION` and `ROOT_SYNC_MODE` support to
  `scripts/deploy-root-app.sh`; `HEAD` remains the stable default and non-HEAD
  revisions default to manual Root sync.
- Documented Root `OutOfSync / Healthy` as the expected bounded state after
  feature child overrides and prohibited Root resync until validation ends.
- Inserted the recovery increment before observability UI work: dashboards now
  begin at v0.11.4 and clean-room final acceptance moves to v0.11.9.

### Boundary

- Active local manifests still declare `HEAD`; no feature branch is committed.
- The workflow does not publish images, mutate AWS, auto-promote a Canary,
  change v0.10 orchestration, or claim v0.11.3 live acceptance.
- The completed v0.11.2 local telemetry path is operator-validated; AWS live
  telemetry evidence remains pending for later bounded qualification.

## v0.11.2

### Added

- Added bounded HTTP request and PostgreSQL dependency counters and histograms
  suitable for later availability, error-rate, and latency SLIs.
- Added an application-owned ServiceMonitor with scrape limits, stable
  `demo-api`, `demo-api-stable`, and `demo-api-canary` job names, and six
  Pod-derived release-correlation target labels.
- Added the v0.11.2 machine-readable contract, positive/negative validator,
  implementation guide, and one-command local live telemetry check.

### Changed

- Moved demo-api scrape ownership out of kube-prometheus-stack
  `additionalServiceMonitors` and into the demo-api Helm Chart.
- Reused the accepted v0.10 deterministic release ID rather than changing
  image publication, environment Promotion, rollback, or release values.
- Advanced the demo-api Chart to `0.5.0` and updated active observability and
  validation documentation for the new metric schema.

### Boundary

- v0.11.2 claims offline implementation only; local and aws-dev live evidence
  remain required.
- Grafana, recording rules, Alertmanager, centralized logs, tracing, SLOs,
  specialized controller monitors, and SLI-based Rollout gates remain deferred.

## v0.11.1

### Added

- Added a pinned `kube-prometheus-stack` `88.5.0` Argo CD Application for the
  active local environment and shared AWS dev/test/prod declarations.
- Added Prometheus Operator, Prometheus, kube-state-metrics, node-exporter,
  CRDs, bounded resources, environment-specific retention, and a
  compatibility ServiceMonitor that preserves the current stable/canary job
  names.
- Added encrypted `gp3-observability` storage with environment and cleanup
  tags, system-node placement, all-worker node-exporter toleration, and
  Prometheus/application scrape NetworkPolicy paths.
- Added a machine-readable v0.11.1 contract, positive/negative offline
  validator, migration guide, local runtime checks, and AWS live-validation
  boundary.

### Changed

- Moved the active metrics namespace from `monitoring` to `observability` and
  changed the local AnalysisTemplate endpoint to the stable Operator-managed
  Prometheus Service.
- Updated monitoring, restart, analysis-enablement, and full local validation
  helpers so they no longer assume a hand-written `deployment/prometheus`.
- Retained `platform/monitoring/prometheus` only as historical v0.1 material;
  no active Argo CD Application references it.

### Boundary

- Grafana, Alertmanager, default alert rules, Loki, Alloy, tracing, SLOs,
  SLI-based Rollout gates, Thanos, and remote write remain deferred.
- v0.11.1 claims offline implementation only. Local and AWS live facts must be
  recorded after deployment; no v0.10 release-orchestration, production
  approval, automatic merge, environment creation, or rollback boundary is
  changed.

## v0.11.0

### Added

- Added the v0.11 Observability and SRE design foundation with an incremental
  metrics, telemetry, dashboard, alerting, logging, tracing, SLO,
  environment-qualification, and final-acceptance sequence.
- Added a machine-readable foundation contract for environment profiles,
  stable resource attributes, release correlation, extensible OpenTelemetry
  transport, cardinality and privacy controls, production governance, and
  clean-room dev/test/prod-live acceptance.
- Added offline positive and negative validation that rejects automatic
  environment creation, automatic merge or rollback, production Kubernetes
  writes, missing production approval, backend-coupled application tracing,
  unbounded telemetry dimensions, AI infrastructure ownership drift, and
  accidental v0.10 evidence mutation claims.

### Changed

- Split the former combined v0.11 scope into v0.11 Observability and SRE plus
  v0.12 Production Readiness Capstone, and reserved v1.0 for the stabilized
  production-ready commercial baseline.
- Recast v1.1 as integration with the separate `ai-infra-blueprints`
  repository and moved lightweight, human-governed AIOps to v1.2.
- Corrected active documentation that still referred to observability as a
  v1.0 capability while preserving historical Changelog and archive text.
- Registered the v0.11.0 contract validator in reusable CI quality gates and
  protected the new design boundary through CODEOWNERS.

### Boundary

- v0.11.0 deploys no Prometheus, Grafana, Alertmanager, Loki, Alloy,
  OpenTelemetry Collector, or tracing backend and changes no application,
  Terraform, AWS, Kubernetes, GitHub workflow permission, or release value.
- The accepted v0.10 evidence remains immutable. Environment creation, pull-
  request merge, production mutation, and rollback remain outside automation.

## v0.10.8.7

### Post-tag image security hotfix

- Removed the `v*` tag trigger from demo-api image publication because GitHub
  does not evaluate path filters for tag pushes; repository closure tags now
  retain the already accepted image identity without rebuilding it.
- Added a Debian security refresh to the runtime base stage and forced BuildKit
  to pull the configured base before building a publish candidate.
- Pinned Trivy CLI behavior to v0.74.0 in CI and added an optional local exact-
  digest scan using the non-deprecated `--pkg-types` flag.
- Added static negative contracts for tag-triggered builds, missing base pulls,
  missing OS security refreshes, and scanner-version drift.
- Changed closed final-evidence validation to replay each append-only record
  against its recorded historical control-plane SHA, allowing later security
  changes without rewriting v0.10 acceptance history.

### Security finding

- The accepted v0.10.8 digest was rescanned on 2026-08-18 and reported
  CVE-2026-53615 in nine binary packages from Debian's `util-linux` source
  package. All were HIGH, none were CRITICAL, and Debian supplied the fixed
  trixie security version `2.41.5-0+deb13u1`.
- The final tag and evidence remain immutable historical records. This hotfix
  creates a new scanned image candidate; it does not mutate the accepted
  digest, recreate an AWS environment, or claim a new live Qualification.

## v0.10.8.6

### Fixed chapter 17 evidence-only PR validation

- Replaced the unconditional empty-final-directory rejection with an explicit
  two-state lifecycle: no record is valid before closure, while every proposed
  or committed record must pass the full final-evidence validator.
- Added an evidence-present dispatch fixture so the quality gate exercises the
  chapter 17 state instead of testing only an empty repository.
- Documented the separate repair-PR and regenerated evidence-only PR sequence
  when the obsolete empty-directory rule has already rejected an unmerged
  final record.

### Boundary

- This repair does not accept a record merely because it exists. Invalid
  structure, stale Scope, mismatched Release or Bundle identity, and unsafe
  acceptance claims still fail through
  `scripts/validate-v0.10-final-evidence.py`.
- No live checkpoint, AWS environment, runner, Promotion, rollback, Bundle, or
  cleanup audit must be repeated. The regenerated final input changes only the
  current reviewed `main` SHA and actual recording time.

## v0.10.8.5

### Clarified before final evidence creation

- Added one run/PR identity convention that distinguishes top-level workflow
  run IDs from Job IDs, `runner_id`, PR validation runs, image-publish runs,
  and PR numbers.
- Reworked sections 6, 12, 13, and 15 into dispatch, observe, record, review,
  merge, and refresh checkpoints with explicit final-input field names.
- Defined `supersededRelease` as stale, human-closed Release PR A; the selected
  and merged PR B has no independent final-input field.
- Added a complete section-to-field mapping for every required run and PR,
  including the aws-test Promotion run/PR distinction.
- Made `validatedControlPlaneSha` the clean latest `main` after all acceptance
  repair merges and made `recordedAt` the actual UTC time immediately before
  final evidence writing.
- Added an executable final-input preflight that rejects placeholders, zero PR
  numbers, malformed run IDs, stale main SHA, and malformed UTC timestamps.

### Boundary

- This documentation and contract-test repair changes no Qualification Scope,
  existing Bundle, Release identity, application, AWS resource, Terraform,
  runner, IAM, RBAC, Promotion, rollback, or cleanup fact. Earlier live
  checkpoints do not need to be repeated.

## v0.10.8.4

### Fixed after live disposable-environment cleanup

- Made environment-variable destroy confirmation explicit instead of printing
  an interactive prompt that the script had already satisfied.
- Added an interrupted-destroy continuation path: when EKS is already absent,
  the entrypoint skips Kubernetes pre-cleanup, resumes the existing Terraform
  destroy, and retires environment-tagged Karpenter Instant Fleet records.
- Added exact ENI inventory and made EC2-native instance, volume, ENI, and NAT
  checks authoritative over eventually consistent Resource Groups Tagging API
  history. Unknown tagged resource types and active Fleets still fail closed.
- Added offline regression cases for missing-cluster continuation, stale tagged
  EC2 history, live ENIs, active/terminal Fleets, and unexpected tagged types.
- Expanded final-acceptance sections 16 and 17 with executable UTC cleanup
  timestamp capture, persistence, validation, and final-evidence population.

### Boundary

- This repair does not recreate EKS, delete Terraform state, weaken residual
  checks, change application desired state, or alter Promotion, Qualification,
  rollback, IAM, RBAC, or production behavior.

## v0.10.8.3

### Fixed after live rollback-boundary execution

- Distinguished an intentionally historical, workflow-proven rollback PR from
  an obsolete ordinary Promotion PR in the required release-currentness check.
  Stale, superseded, ambiguous, and cross-environment Promotion identities
  remain rejected.
- Bound the rollback exception to the exact target-only historical commit,
  expected current Release ID, captured `main` SHA, restored immutable
  identity, PR title/body metadata, rollback branch run ID/attempt, and the
  originating manual `demo-api-rollback.yaml` workflow run. A `rollback/`
  prefix alone grants no bypass.
- Made `expected_current_release_id` mandatory and exposed the documented
  reusable rollback outputs from the job boundary.
- Added positive governed-rollback fixtures plus negative missing-provenance
  and wrong-workflow fixtures so the live PR/currentness conflict cannot
  regress behind otherwise-passing rollback-generation tests.
- Rewrote final-acceptance section 14 as a command-by-command procedure for
  Release derivation, historical candidate resolution, dispatch, run/PR
  identity recording, required-check review, and close-without-merge closure.

### Boundary

- This repair changes no Demo workload, Helm release identity, Qualification
  Scope, Terraform, IAM, RBAC, AWS resource, automatic merge, automatic
  rollback, or Kubernetes access. A real rollback still requires a protected
  PR and human merge; the final acceptance drill still closes its PR.

## v0.10.8

### Fixed after clean-room execution

- Added a deterministic post-runtime/pre-Bundle interruption checkpoint so a
  healthy environment cannot complete too quickly to exercise cancellation.
- Distinguished workflow `run ID` from self-hosted `runner_id`, added live and
  offline runner-isolation validation, and made distinct automatically
  unregistered runner registrations part of final acceptance evidence.
- Documented the append-only recovery path when a same-runner Bundle was
  already merged: preserve it, wait for a legitimate requalification state,
  then repeat both interruption and resume with clean `--ephemeral`
  registrations.
- Corrected first-create aws-dev instructions to use the guarded EKS endpoint
  CIDR helper, explicit cost-controlled logging input, and current runtime-role
  fields in the untracked Terraform variables.
- Split the trusted runtime IAM lifecycle from disposable EKS access: the new
  account-bootstrap `runtime-identities` root retains exact-subject,
  exact-cluster read roles while dev/test roots own only EKS access entries.
  This lets the live pre-create probe report `blocked / environment_absent`
  instead of failing earlier as `oidc_denied` after a complete environment
  destroy.
- Expanded the final Runbook with the exact source-A/source-B/release-A/
  release-B ordering, GitHub bot workflow approval timing, deterministic
  Release ID extraction, final evidence field mapping, and the practical
  single-maintainer review limitation.
- Added `scripts/derive-demo-api-release-id.py` and structural negative tests
  that reject environment-owned runtime roles, missing persistent identity
  state, wildcard OIDC trust, or widened IAM permissions.

### Added

- Machine-readable final acceptance contract for protected-main
  dev/test/prod-static acceptance, interruption recovery, supersede, manual
  rollback boundary, disposable-environment cleanup, and closure ordering.
- Strict v0.10 final-evidence schema, repository-bound writer, reference/hash
  validator, operator input template, and append-only `evidence/v0.10/` layout.
- `docs/V0.10_FINAL_ACCEPTANCE_RUNBOOK.md` with GitHub settings, activation
  variables, exact orchestrator commands, environment rebuild, Canary review,
  prod-static Promotion, destroy/audit, evidence-only PR, and tag procedure.
- Offline positive/negative acceptance tests for required checkpoints,
  placeholder identities, duplicate PR claims, cleanup residuals, active
  runners, production runtime/cluster claims, and automatic rollback.

### Changed

- Integrated the v0.10 final acceptance validator into repository quality
  gates and protected its contracts, scripts, Runbook, and evidence through
  CODEOWNERS.
- Marked the v0.10 Roadmap implementation complete. Live acceptance remains an
  explicit post-merge operation and is represented only by its reviewed final
  evidence record.

### Boundary

- v0.10.8 adds no Terraform/IAM/RBAC, Helm runtime change, automatic merge,
  automatic environment creation, production cluster/runtime access,
  Kubernetes write, or automatic rollback. Its acceptance-only workflow input
  can only hold a reviewed manual resume after runtime qualification and fails
  closed before durable Bundle creation.
- Bundle expiry and exact retry/rollback-handoff failure classes use
  deterministic clock/history validation. Live acceptance proves the normal
  Qualification/Promotion path without keeping EKS running for 24 hours or
  deliberately damaging a workload.

## v0.10.7

### Added

- Exact failed-Attempt `retry` using the prior orchestrator run ID, run attempt,
  Release ID, repository identity, and safe retry class.
- Secret-free 14-day orchestration Attempt artifacts containing decision,
  execution outcome, stable reason, recovery class, and optional rollback
  handoff. Attempts are diagnostics and never Promotion evidence.
- Git source-ancestry and same-source build-run supersede handling, including
  ambiguous-order blocking and an explicit human PR-close recommendation.
- Qualification Bundle states for `expiring`, `expired`, `scope_drift`,
  `release_drift`, and `invalid`, plus a 3600-second Promotion validity floor.
- A read-only dev/test rollback candidate resolver and failed Release identity
  recheck in the existing Environment-approved rollback Workflow.
- `docs/RELEASE_FAILURE_RECOVERY.md` and offline retry, Attempt, supersede,
  expiry/drift, and rollback-handoff behavior tests.

### Fixed

- Made `operation=status` strictly read-only. It now always returns
  `dispatchAuthorized=false`, and every stage/disabled-report job also rejects
  status execution even when repository activation variables are enabled.

### Boundary

- v0.10.7 never automatically closes or merges a PR, dispatches or merges a
  rollback, writes Kubernetes, creates an AWS environment, runs production
  qualification, or accepts a partial GitHub job re-run as unified evidence.
- Live interrupted-run, supersede, expiry, rollback, cost cleanup, and final
  clean-room acceptance remain in v0.10.8.

## v0.10.6

### Added

- Repository-variable-gated `aws-test -> aws-prod` Promotion preparation from
  the merged, fresh, scope-valid aws-test Qualification Bundle.
- A required protected `aws-prod` GitHub Environment approval before the
  release-only PR preparation job can execute.
- Offline production orchestration tests covering fresh/stale test Bundles,
  exact ordered edges, source-bound Bundle paths, existing prod PR reuse,
  completed GitOps state, and forbidden runtime/merge behavior.
- `docs/AWS_PROD_CONTROLLED_PROMOTION.md` with GitHub setup, state semantics,
  accepted facts, permissions, and validation commands.

### Changed

- Upgraded application, stage, orchestrator, snapshot, and decision contracts
  to v0.10.6 while retaining the v0.10.5 Qualification Bundle format so
  existing reviewed test Bundles remain consumable.
- Extended Bundle-mode Promotion to the two exact ordered edges:
  `aws-dev -> aws-test` and `aws-test -> aws-prod`.
- Authorized `prepare-prod-promotion` only after test qualification succeeds;
  the orchestrator selects the aws-test Bundle path and SHA-256 from the same
  protected-main snapshot.

### Boundary

- v0.10.6 may prepare a production release-only PR after Environment approval.
  It never merges the PR, accesses AWS/EKS, writes Kubernetes, creates an
  environment, runs production qualification, applies Terraform, triggers
  rollback, or mutates Secrets/databases. `complete` means the GitOps release
  file reached prod, not that production runtime was validated.

## v0.10.5

### Added

- Repository-variable-gated preparation of the reviewed `aws-dev -> aws-test`
  release-only PR from a merged, fresh, scope-valid aws-dev Qualification
  Bundle.
- A separate `DEMO_API_AWS_TEST_QUALIFICATION_ENABLED` switch plus the explicit
  `reviewed-and-completed` resume input after the existing guarded Canary
  completion helper.
- Deterministic aws-test qualification Scope, dev/test Bundle schema support,
  same-run test static/runtime composition, and append-only reviewed aws-test
  Bundle PRs.
- Offline positive and negative tests for Bundle/legacy input isolation,
  Canary-gate bypass, Rollout and AnalysisRun identity checks, stale main,
  duplicate PRs, automatic merge, Kubernetes writes, and production dispatch.

### Changed

- Upgraded application, stage, orchestrator, snapshot, decision, runtime, Scope,
  and Bundle contracts to v0.10.5.
- Extended the planner with `prepare-test-promotion`,
  `review-and-complete-test-canary`, and `qualify-aws-test` transitions while
  preserving the historical manual static/runtime evidence Promotion mode.
- Generalized Qualification Bundle collection and validation to `aws-dev` and
  `aws-test`; each environment retains an independent deployment Scope.

### Boundary

- v0.10.5 creates only reviewed PRs. It never merges a PR, promotes or aborts a
  Rollout, syncs Argo CD, writes Kubernetes, creates an EKS environment, applies
  Terraform, rebuilds an image, triggers rollback, or prepares aws-prod.

## v0.10.4

### Added

- Repository-variable-gated `qualify-aws-dev` orchestration after a reviewed
  aws-dev release reaches protected `main`.
- Static `artifact-only` qualification mode bound to the exact orchestrated
  control-plane SHA, while retaining the v0.9 reviewed static-evidence PR mode.
- Deterministic aws-dev qualification-scope contract and path/content hashing
  across Helm, release/environment values, Argo Application/overlay,
  ExternalSecret, NetworkPolicy, and runtime RBAC inputs.
- Self-contained Qualification Bundle schema, writer, validator, same-run
  artifact binding, append-only evidence path, and qualification-only PR
  Workflow.
- Positive and negative offline tests for cross-run artifacts, wrong
  environment/identity, stale release/scope, extended expiry, secret-like
  fields, duplicate Bundle PRs, Promotion dispatch, production access, and
  automatic merge.

### Changed

- Upgraded orchestration snapshot and decision contracts to v0.10.4 and made
  reviewed aws-dev Bundles the durable qualification fact for the automated
  path.
- Added a shared 900-second passive convergence window with 15-second polling
  for exact Argo revision and workload readiness.
- Updated reusable-stage and application contracts, quality gates, README,
  Roadmap, trusted-runtime guidance, evidence layout, and orchestrator docs.

### Boundary

- v0.10.4 does not rebuild images, dispatch aws-test/aws-prod Promotion or
  qualification, merge PRs, create EKS environments, apply Terraform, sync
  Argo CD, mutate Rollouts/Secrets/databases, or trigger rollback.

## v0.10.3.2

### Fixed

- Replaced full repository copies in trusted-runtime mutation tests with a
  filtered validation-tree copy that excludes local Terraform provider caches,
  state, plans, and real variable files.
- Added a self-contained fixture regression proving local artifacts are
  excluded while `.terraform.lock.hcl` and tracked Terraform configuration are
  retained.
- Removed each mutation workspace immediately after its expected rejection so
  disk use remains bounded for the duration of the validator.

### Boundary

- v0.10.3.2 changes only offline validation workspace construction. It changes
  no Workflow, OIDC trust, IAM permission, EKS access entry, Kubernetes RBAC,
  runtime result, Promotion, evidence, or production-access behavior.

## v0.10.3.1

### Fixed

- Formatted the GitHub Actions runtime identity module with canonical
  `terraform fmt` alignment.
- Repackaged the runtime qualification RBAC Application as an independent
  Kustomize directory so dev/test overlays no longer load an individual YAML
  file outside their build root.
- Updated active-revision and trusted-runtime validation for the new
  Application path.
- Added negative coverage for direct cross-directory YAML loading and rendered
  assertions that runtime qualification RBAC exists in dev/test but not prod.

### Boundary

- v0.10.3.1 changes no Workflow, IAM, EKS access-entry, Kubernetes RBAC, or
  production-access semantics. It is a packaging and validation repair for
  v0.10.3.

## v0.10.3

### Added

- Protected-main demo-api runtime qualification Workflow with separate
  GitHub-hosted preflight and environment-labeled ephemeral self-hosted
  execution jobs.
- Machine-readable trusted executor and runtime-result contracts covering
  dev/test identities, immutable inputs, qualified/blocked/failed outcomes,
  artifact hygiene, and production exclusion.
- GitHub OIDC IAM and EKS access-entry module with exact repository Environment
  subjects, exact-cluster `eks:DescribeCluster`, and dev/test-isolated roles.
- GitOps-managed `argocd` and `startup-apps` read-only Roles and RoleBindings
  for Argo Application, Deployment/Rollout, AnalysisRun, Pod imageID, Service,
  Ingress, and Event facts.
- Runtime collector and secret-field-rejecting result writer covering current
  main, release identity, cluster presence, endpoint reachability, negative
  RBAC checks, Argo convergence, rollout/analysis health, Pod digest, and HTTPS
  identity.
- Offline positive and negative validation for GitHub-hosted fallback,
  untrusted triggers, arbitrary target inputs, production access, wildcard
  OIDC trust, IAM/Kubernetes writes, Secret access, Terraform execution, and
  sensitive artifact fields.
- Trusted runtime setup, security, result, queue behavior, branch validation,
  and post-merge live acceptance documentation.

### Changed

- Linked the v0.10 application contract to the runtime executor Workflow and
  result contracts.
- Added the trusted runtime validator to the repository-wide quality gate and
  reviewed the pinned AWS credential Action.
- Added optional, disabled-by-default runtime identity instances and outputs to
  the aws-dev and aws-test Terraform roots only.
- Marked v0.10.3 delivered and made it the repository's current checkpoint.

### Boundary

- v0.10.3 does not dispatch runtime qualification from the orchestrator,
  create or merge PRs, create EKS environments, register persistent runners,
  store long-lived AWS keys, write durable qualification evidence, mutate
  Kubernetes, or provide aws-prod runtime access. Those automation and
  evidence integrations remain v0.10.4 through v0.10.8.

## v0.10.2

### Added

- Event-driven demo-api release orchestrator for protected-main source,
  release, and evidence changes plus manual `start`, `status`, and `resume`.
- Read-only Git and GitHub fact collector that derives release identities from
  exact release/evidence content and discovers matching open PRs targeting
  `main`.
- Deterministic plan engine covering source, dev/test/prod release, runtime and
  static qualification, absent-environment, production approval, stale-main,
  duplicate-PR, and complete states.
- Machine-readable orchestrator, snapshot, and decision contracts plus an
  offline validator with positive scenarios and unsafe negative mutations.
- Release-orchestrator documentation covering operations, fact sources,
  idempotency, resume, evidence freshness, concurrency, and security boundaries.

### Changed

- Linked the application and reusable-stage contracts to the implemented
  v0.10.2 orchestrator contract.
- Added the event-driven orchestrator validator to the repository-wide CI
  quality gate.
- Marked v0.10.2 delivered and made it the repository's current checkpoint.

### Boundary

- v0.10.2 is plan-only. It does not dispatch reusable delivery stages, create
  or merge PRs, access AWS/EKS, create environments, collect trusted runtime
  evidence, or bypass production Environment and reviewed-PR controls.

## v0.10.1

### Added

- Machine-readable reusable delivery-stage contract for image publishing,
  static qualification, ordered environment Promotion, and rollback handoff.
- Typed `workflow_call` inputs and stable workflow outputs on the four existing
  delivery workflows while retaining their v0.9 push or manual entrypoints.
- Offline reusable-stage validator with positive checks and negative mutations
  for unsafe runner access, AWS credentials, automatic merge, environment
  creation, skipped test Promotion, PR-code execution, missing production
  coverage, and incomplete stage outputs.
- Reusable delivery-stage documentation covering compatibility, stage
  interfaces, durable results, retry scope, and the deferred trusted-runtime
  boundary.

### Changed

- Linked the v0.10 application contract to the reusable stage contract.
- Added the reusable-stage validator to the repository-wide CI quality gate.
- Marked v0.10.1 delivered and made it the repository's current checkpoint.

### Boundary

- This increment makes the existing GitHub-hosted workflows reusable but does
  not add the event-driven orchestrator, automatic PR merge, AWS OIDC/IAM/RBAC,
  EKS access, runtime qualification workflow, or unified qualification bundle.

## v0.10.0

### Added

- Machine-readable demo-api release-orchestration contract defining the
  environment chain, immutable release identity, execution policies, runner
  boundaries, production controls, and resumable phase transitions.
- Draft 2020-12 release-state JSON Schema plus a derived-state example that
  separates release phase from progressing, waiting, blocked, failed,
  superseded, and completed status.
- Offline contract validator with positive checks and in-memory negative
  mutations for environment skipping, production auto-merge, automatic EKS
  creation, unsafe runner access, duplicate release paths, unsafe release IDs,
  missing production approval, and invalid state transitions.
- Release orchestration model documentation covering durable fact sources,
  idempotency, resume, absent-environment behavior, execution boundaries, and
  deferred implementation scope.

### Changed

- Started the v0.10 roadmap while retaining v0.9 as a completed version line.
- Added the release-orchestration contract validator to the repository-wide CI
  quality gate before Docker- and Helm-dependent validation.

### Boundary

- This increment adds contracts, documentation, a state example, and offline
  validation only. It does not add an orchestration Workflow, automatic PR
  merge, AWS OIDC/IAM/RBAC, runner registration, EKS creation, or live cluster
  access from GitHub Actions.

## v0.9.8

### Added

- Canonical, command-by-command multi-environment release Runbook covering
  one-time GitHub configuration, immutable image publication, aws-dev and
  aws-test runtime evidence, qualification evidence, ordered Promotion,
  production approval, safe pause/resume, troubleshooting, and cost cleanup.
- Explicit operator checkpoints that distinguish the numeric GitHub
  `evidence_run_id` from the UTC `runtime_evidence_id` and verify that both
  evidence-only PRs are merged before Promotion.
- Single-maintainer portfolio guidance that prevents an impossible GitHub
  Environment approval configuration while retaining the distinct-reviewer
  and self-review prohibition expected for real production teams.

### Changed

- Corrected the clean-room lifecycle example from the invalid
  `release_evidence_run_id` input to the workflow's actual
  `evidence_run_id` input.
- Linked architecture, governance, workflow, and lifecycle documentation to a
  single manual operator entry point.
- Documented when an ephemeral aws-test cluster may be destroyed without
  invalidating a still-fresh, release-bound static test-to-prod Promotion.

### Boundary

- This increment changes documentation and examples only. It does not change
  release workflow behavior, automate PR merges, create a production cluster,
  or pull v0.10 delivery-orchestration scope into v0.9.

## v0.9.7

### Added

- Guarded `off` and `production-parity` EKS control-plane logging profiles
  that preserve each environment's Terraform-managed CloudWatch retention.
- Static profile contracts covering disposable dev/test defaults, complete
  production logging, endpoint-update profile preservation, and formal live
  security validation.
- Terminal EC2 Fleet classification in the post-destroy audit, including
  behavior tests for terminal, expired, active, and unrelated residual cases.
- Cost-aware operations and cleanup-hardening checkpoint documentation.

### Changed

- Defaulted disposable aws-dev and aws-test control-plane log ingestion to
  off while retaining 14-day and 30-day log-group retention respectively.
- Required all five EKS control-plane log types and at least 90-day retention
  in the aws-prod Terraform root.
- Made the dynamic EKS management-IP updater preserve the live logging profile
  unless log types are explicitly supplied.
- Treated `deleted`, `deleted_terminating`, and already-expired Instant Fleet
  records as non-actionable audit history while continuing to fail on active,
  unknown, or unclassifiable Fleet state.
- Recorded the completed dev/test and governed static-prod promotion boundary;
  end-to-end delivery orchestration remains v0.10 scope.

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
- Assigned demo-api in every AWS environment to the Karpenter-managed
  `application-ondemand` tier, leaving the Managed Node Group for stable
  platform capacity and Spot/FIS tiers for controlled exercises, with static
  rendering and live aws-dev placement validation.
- Made the On-Demand scale test baseline-aware and removed pool-wide NodeClaim
  deletion so a failed exercise cannot evict the steady demo-api workload.
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
