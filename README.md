# startup-devops-baseline

A local-first DevOps, GitOps, progressive delivery, and AWS EKS infrastructure baseline for early-stage teams.

Current development checkpoint: `v0.11.6.2.3.1-demo-api-runtime-artifact-preflight-repair`.
It retains the accepted `v0.11.6.2.3-local-minimal-tracing-closure` and adds a
runtime-artifact preflight before its two live correlation runs.
The local profile deploys one private, bounded Loki Monolithic instance, an
Alloy DaemonSet for node-local `startup-apps` Pod logs, and a separate
one-replica Alloy Deployment for cluster Kubernetes Events. Event read
positions use a 256Mi local PVC so collector Pod replacement does not replay
the Kubernetes Event TTL window. The existing Grafana instance receives one
non-default, non-editable, proxy-mode Loki data source. Pod and Event streams
both preserve the exact six-label index contract. Loki storage remains
disposable and limited to a 2 GiB `emptyDir` with 24-hour retention. Dashboards
and AWS logging remain outside this increment. v0.11.6.2.0 adds application-
side W3C propagation, bounded HTTP/PostgreSQL spans, shared release identity,
and real log correlation while keeping OTLP export disabled. v0.11.6.2.1 now
adds one private traces-only OTel Collector Deployment and one repository-owned
Tempo 3.0.3 Monolithic Deployment with bounded disposable local storage. The
application export and Grafana integration were deliberately separate from
that runtime increment. v0.11.6.2.2 now enables the already accepted exporter
only in the local App-of-Apps, validates a real `/version` SERVER span and its
correlated Loki JSON record, and provisions a private Grafana Tempo data source
plus a Loki `TraceID` derived field. Trace identifiers remain outside Loki's
label index, and no application image rebuild is required. Repair
`v0.11.6.2.1.1` corrects only the synthetic acceptance client: OTLP/JSON trace
and span identifiers are now hexadecimal, HTTP rejection bodies remain visible,
and Tempo/Collector diagnostics are selected explicitly. It changes no runtime
resource and requires neither reconciliation nor an image rebuild. Its runtime
predecessor is
`v0.11.6.2.1-private-local-otel-collector-tempo-runtime`. Repair
`v0.11.6.1.2.1` co-schedules the Event-position claim and
its consumer Application for `WaitForFirstConsumer` storage, makes Argo CD
sync waits bounded, and repairs exact historical Application counting. See
`docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md` and
`docs/V0.11.6.1.2_KUBERNETES_EVENTS_GRAFANA_LOKI.md`.
Repair `v0.11.6.1.2.2` normalizes the temporary acceptance Event timestamp to
the six-digit UTC precision required by Kubernetes `MicroTime`; it changes no
deployed workload. See
`docs/V0.11.6.1.2.2_KUBERNETES_EVENT_MICROTIME_ACCEPTANCE_REPAIR.md`.
Closure `v0.11.6.1.3` composes the platform, Pod-log, Events, Loki, and
Grafana checks into one repeatable entrypoint, adds strict successful-path
Event cleanup, preserves accepted Loki history after source deletion, and
retains the version-specific `WaitForFirstConsumer` incident record. It changes
no deployed workload. See
`docs/V0.11.6.1.3_LOCAL_LOGGING_END_TO_END_CLOSURE.md`.
The active tracing runtime is documented in
`docs/V0.11.6.2.1_PRIVATE_LOCAL_OTEL_COLLECTOR_TEMPO_RUNTIME.md`; its accepted
application contract is
`docs/V0.11.6.2.0_DEMO_API_OPENTELEMETRY_TRACING_CONTRACT.md`.
The corresponding accepted checkpoint identifier is
`v0.11.6.2.0-demo-api-opentelemetry-tracing-contract`.
Its accepted logging predecessor checkpoint is
`v0.11.6.1.3-local-logging-end-to-end-closure`.
Its reconciliation predecessor checkpoint is
`v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair`.
Its accepted Pod-log predecessor checkpoint is
`v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair`.
Its runtime predecessor checkpoint is
`v0.11.6.1.0-structured-demo-api-logging-runtime`.
The architectural foundation remains
`v0.11.6.0-centralized-logging-minimal-tracing-foundation`.

This repository demonstrates a practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, Argo Rollouts, GHCR image publishing, Prometheus, and a small demo API service.

The repository now contains the completed local progressive-delivery and AWS
EKS baselines, isolated On-Demand and Spot application NodePools, a tag-scoped
AWS FIS drill, and a GitOps-managed CloudNativePG PostgreSQL persistence,
high-availability, S3 backup, point-in-time recovery, application integration,
and primary-failover baseline. Reusable CI quality gates protect both
pull-request validation and GHCR image publishing. Published application
images now carry a SHA tag, immutable OCI digest, structured source identity,
and GitHub build-provenance attestation. Successful main-branch builds now
turn that identity into a reviewable aws-dev GitOps promotion pull request.
The same immutable identity can then move only through the ordered
`aws-dev -> aws-test -> aws-prod` chain, with one target-scoped, reviewable PR
per transition and no direct cluster access from GitHub Actions. Cross-
environment movement now requires a fresh, reviewed source-release evidence
record, a separately reviewed source-runtime evidence record, target GitHub
Environment approval, and CODEOWNERS review. AWS test and production desired
state now use Argo Rollouts with ALB weighted target groups, canary-local Web
AnalysisRuns, and explicit manual progression. The same
governance boundary applies to environment-scoped rollback PRs.
Promoted values and live workloads now retain enough delivery metadata to
correlate source, build, Git promotion, Argo CD reconciliation, Pod image ID,
and the application-reported version. A manual rollback workflow can now
restore a previously reviewed, metadata-aware desired state through another
values-only pull request. The AWS environment now also enforces namespace and
admission guardrails plus default-deny NetworkPolicy isolation for application
and CloudNativePG data workloads, with explicit runtime-validated traffic
paths. AWS Secrets Manager, exact-secret IRSA, a namespaced External Secrets
Operator deployment, and an active ExternalSecret now provide the demo-api
PostgreSQL credential without committing the value to Git or Terraform state.
The v0.9 lifecycle now also defines a clean-room aws-dev/aws-test acceptance
sequence, guarded ephemeral test creation, reviewed canary completion,
CloudNativePG recovery validation, dependency-aware test destruction, exact
AWS residual-cost checks, and tamper-evident final closure evidence. The
repository remains intentionally smaller than a full production platform.
The v0.8 finalization added the `demo.dev.aureumstack.com` Route 53 endpoint,
ACM-backed HTTPS, HTTP redirection, a runtime-only EKS management `/32`, and
bounded security logging. v0.9 turns this single live AWS baseline into a
cost-aware, multi-environment GitOps promotion model without requiring three
permanently running portfolio clusters. v0.9.7 separates disposable
control-plane logging cost from formal production-parity validation and makes
the cleanup audit aware of terminal Karpenter Instant Fleet history. v0.9.8
provides one canonical, command-by-command operator Runbook for GitHub setup,
evidence collection, ordered Promotion, safe pause/resume, and cost cleanup.
v0.10.0 now defines the deterministic, environment-independent release
identity, derived phase/status model, resumable transition graph, and separated
GitHub-hosted, trusted-runtime, and human approval boundaries that the later
delivery automation increments must implement. This checkpoint is deliberately
offline: it adds no release orchestrator and grants no Workflow AWS/EKS access.
v0.10.1 upgrades the existing image, static qualification, ordered Promotion,
and rollback workflows into reusable delivery stages with typed inputs,
machine-readable outputs, an offline stage contract, and unchanged manual
entrypoints. The reusable stages remain GitHub-hosted, PR-oriented, and unable
to access AWS or EKS; runtime qualification remains reserved for the later
trusted executor.
v0.10.2 adds the event-driven, read-only release orchestrator. Protected-main
source, release, and evidence events plus manual `start`, `status`, and `resume`
now produce a deterministic snapshot and next-action decision, discover and
reuse matching open PRs, reject ambiguous duplicates, and block safely if
`main` changes during derivation. This checkpoint remains plan-only: it grants
no write, AWS, or EKS permission and does not dispatch a reusable stage.
v0.10.3 implements the separately trusted runtime qualification boundary for
`aws-dev` and `aws-test`: protected-main preflight, environment-labeled
ephemeral self-hosted execution, short-lived GitHub OIDC, exact-cluster IAM,
namespaced read-only EKS RBAC, release-bound live checks, and a secret-free
temporary result artifact. It is not yet dispatched by the orchestrator and
does not implement production runtime access.
v0.10.3.1 repairs the dev/test-only RBAC Application assembly so standard
Kustomize load restrictions render every AWS overlay successfully, and brings
the runtime identity module into canonical Terraform formatting. No execution
or authorization boundary changes in this patch release.
v0.10.3.2 bounds trusted-runtime offline mutation-test storage by excluding
local Terraform caches, state, plans, and real variable files from temporary
repository copies, while retaining dependency lock and tracked configuration
files. It changes no runtime or authorization behavior.
v0.10.4 activates repository-variable-gated aws-dev qualification after a
reviewed dev release reaches `main`. It combines same-run static and trusted
runtime results into one scope-bound, self-contained Qualification Bundle PR,
waits passively for GitOps convergence, and stops before aws-test Promotion.
It neither rebuilds the image nor merges a PR, creates a cluster, syncs Argo
CD, accesses production, or dispatches rollback.
v0.10.5 consumes the merged, still-fresh aws-dev Bundle to prepare a reviewed
dev-to-test release-only PR. After that PR is merged, aws-test Canary progression
remains an explicit human action; only a manual `reviewed-and-completed` resume
may run same-run static/runtime qualification and create the reviewed aws-test
Bundle PR. v0.10.6 consumes that merged, still-fresh test Bundle to prepare a
reviewed test-to-prod release-only PR behind the protected `aws-prod` GitHub
Environment. The workflow never merges the PR, obtains production runtime
access, or writes Kubernetes.
v0.10.7 hardens recovery: manual `status` is now strictly read-only, `retry`
accepts only the exact prior safely retryable Attempt, newer Releases supersede
older unfinished work without automatically closing PRs, Bundle expiry and
drift are explicit, and selected dev/test runtime failures can produce a
read-only governed rollback handoff. The orchestrator still never dispatches a
rollback, merges a PR, or gains production runtime access.
v0.10.8 closes the version line with a protected-main clean-room acceptance
contract, exact dev/test/prod-static Runbook, interruption and environment
restoration checkpoints, deterministic expiry/retry/rollback-handoff tests,
dependency-aware dev/test cost cleanup, and repository-bound append-only final
evidence. The interruption checkpoint is a bounded post-runtime/pre-Bundle
hold, and final evidence rejects an interrupted/resumed pair that reused the
same registered self-hosted `runner_id` or left either runner registered. No
success evidence is included before the real live sequence runs.
v0.10.8.3 repairs the live rollback boundary discovered during that sequence:
the required currentness gate now distinguishes a workflow-proven historical
rollback from a superseded ordinary Promotion without trusting a branch prefix
alone, and the final Runbook provides the exact operator commands and evidence
mapping for the close-without-merge rollback drill.
v0.10.8.4 repairs the live cleanup boundary: interrupted destroys can continue
after EKS is already absent, Karpenter Instant Fleet request records are
retired, and exact EC2 checks distinguish active cost-bearing resources from
eventually consistent tag history. Final acceptance now captures each passing
cleanup audit's actual UTC timestamp with executable commands.
v0.10.8.5 completes the operator evidence mapping before closure: every
checkpoint now identifies the exact workflow run and PR to record, Release PR
A is distinguished from selected Release PR B, and the final input has
executable current-main, UTC timestamp, and placeholder/zero-value preflight
commands.
v0.10.8.6 fixes the final closure lifecycle so an empty directory is accepted
before chapter 17 and a proposed or committed final JSON is fully validated
during the evidence-only PR instead of being rejected merely for existing.
v0.10.8.7 is the post-tag image-security hotfix: closure tags no longer rebuild
demo-api, Debian fixable security updates are installed before publication,
Trivy v0.74.0 behavior is reproducible locally and in CI, and sealed v0.10
evidence is replayed against its recorded historical control plane.
v0.11.0 begins the Observability and SRE line with an environment-aware design
contract, stable telemetry and release-correlation conventions, an extensible
OpenTelemetry foundation, explicit cost and security profiles, and preserved
human production controls. It deploys no monitoring component and changes no
v0.10 acceptance evidence or release-orchestration behavior.
v0.11.1 replaces the active hand-written local Prometheus deployment with a
pinned Prometheus Operator metrics foundation and adds cost-aware AWS
dev/test/prod declarations. The stack includes Prometheus,
kube-state-metrics, node-exporter, bounded retention, encrypted gp3 storage,
explicit scrape NetworkPolicy, and compatibility with the existing local
Canary query. Grafana, Alertmanager, logs, tracing, SLOs, and telemetry-based
release gates remain later v0.11 increments.
v0.11.2 moves demo-api discovery into its own Helm Chart and adds bounded HTTP
and PostgreSQL dependency metrics. Prometheus target labels now correlate each
selected Pod with its environment, application version, deterministic release
ID, source commit, and image digest without changing the accepted v0.10 build,
Promotion, rollback, or production-approval workflows. Dashboard, alerting,
logging, tracing, and SLO work remains deferred.
v0.11.3 adds a parameterized and reversible local feature-revision GitOps
workflow. It prevents Root self-heal from silently returning same-repository
children to `HEAD`, verifies the deployed revision, Chart, ServiceMonitor and
Prometheus address, preserves manual Canary progression, and restores the
stable automated `HEAD` declaration after testing.
v0.11.4.1.1 provisions immutable Delivery, Data, and Platform Grafana
Dashboards from the accepted controller and dependency recording rules. Local
acceptance requires delivery, demo-api dependency, and platform rule data while
explicitly allowing CloudNativePG panels to remain no-data outside the AWS
profile.
v0.11.4.2.0 adds the capacity and resource-efficiency signal layer without a
new exporter, cost system, Dashboard, or automation action.
v0.11.4.2.1 adds the immutable Capacity and Resource Efficiency Dashboard and
consumes all twenty accepted rules without raw metric, scheduler-exact,
currency-cost, or automation claims. v0.11.4.2.2 repairs the clean replay with
a mandatory fresh local image transition, numeric target-health assertions,
shared bounded telemetry preflight, and Prometheus scrape diagnostics. The
accepted replay closes v0.11.4.
v0.11.5.0 enables one private environment-local Alertmanager per monitoring
profile with bounded storage and resources, stable critical and warning
routing, alert-family inhibition, and Prometheus discovery validation. It adds
no alert rule, external notification integration, central Alertmanager, or HA
claim; actionable alerts and Runbooks remain v0.11.5.1 work. The clean-room
v0.11 acceptance remains the final v0.11.9 increment.
v0.11.5.0.1 repairs the live acceptance check after Alertmanager serialized
`severity = "critical"` as the equivalent canonical `severity="critical"`.
It preserves exact route and inhibition cardinality and requires no runtime
redeployment. Its accepted checkpoint identity is
`v0.11.5.0.1-matcher-normalization-repair`.
v0.11.5.1 adds an exact eight-alert inventory for application, dependency,
delivery, Kubernetes workload, and AWS-profile PostgreSQL collection health.
Every alert has stable routing labels and one version-controlled Runbook; the
clean local baseline must load all rules while keeping them inactive. Its
accepted checkpoint identity is `v0.11.5.1-actionable-alerts-runbooks`.
v0.11.5.1.1 repairs `platform:prometheus_targets_down:count` with
`up == bool 0`, adds `PrometheusTargetDown` as the ninth alert, and introduces
a live recorded-versus-direct query cross-check without deliberately failing
a real target. Its checkpoint identity is
`v0.11.5.1.1-prometheus-target-down-semantics-repair`.
v0.11.5.1.1.1 corrects the live check to use
`operator-diagnostic-recording-rules` and restores the already-required fresh
image transition after the neutral pre-merge baseline. Its accepted checkpoint
identity is `v0.11.5.1.1.1-local-acceptance-path-repair`.
v0.11.5.2.0 proves the complete local alert lifecycle with temporary synthetic
signals and an internal-only webhook sink. Dedicated drill routes continue
into the existing critical and warning routes, resolved payloads are required,
critical-over-warning inhibition is checked in both equal and unequal scopes,
and every temporary object must be removed. External provider delivery and AWS
live execution remain deferred. Its predecessor checkpoint identity is
`v0.11.5.2.0-alert-lifecycle-drill`.
v0.11.5.2.0.1 repairs only the runtime configuration parser after the first
local attempt observed two correctly loaded webhook integrations whose URLs
were rendered as `url: <secret>`. It preserves exact literal desired-state URL
validation and requires no monitoring redeployment. Its predecessor checkpoint
identity is `v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair`.
v0.11.5.2.0.2 repairs the subsequent resolved-delivery phase by explicitly
transitioning each synthetic alert to an empty result before cleanup. Rule
deletion is no longer treated as the state transition, and reruns reject any
active drill alert left in Alertmanager by an earlier failed attempt. Its
predecessor checkpoint identity is
`v0.11.5.2.0.2-alert-resolution-transition-repair`.
v0.11.5.2.0.3 repairs the final cleanup synchronization boundary. After strict
Kubernetes deletion, the drill waits until both temporary alert definitions
disappear from the Prometheus rule inventory before requiring the exact nine
healthy inactive formal alerts. The repaired full local rerun passed, closing
v0.11.5 locally. Its accepted checkpoint identity is
`v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair`.
v0.11.6.0 defines environment-isolated logging and minimal tracing contracts.
v0.11.6.1.0 implements the first application runtime slice: bounded JSON Lines,
one process formatter, quiet successful probes, and Downward API projection of
release identity. v0.11.6.1.1 adds the private local Loki and Alloy Pod-log
path with bounded storage, resources, RBAC, NetworkPolicy, and label
cardinality. v0.11.6.1.2 adds singleton Kubernetes Event collection with
durable read positions and a Git-provisioned Grafana Loki data source; tracing
remains v0.11.6.2 scope.

## Current Version

```text
v0.11.6.1.2-kubernetes-events-grafana-loki
```
The completed v0.8 AWS EKS environment exposes demo-api through
`https://demo.dev.aureumstack.com` with the production-security baseline in
place. v0.9.0 converges every active aws-dev repository Application on `main`
and establishes the formal `aws-dev -> aws-test -> aws-prod` design contract.
Each AWS environment maps to its own EKS cluster and isolated stateful
resources. v0.9.1 separates
stable Helm environment configuration from promotable release identity for
aws-dev, aws-test, and aws-prod. v0.9.2 adds independent Terraform roots and
states plus a shared Kustomize base with dev/test/prod overlays. All three
declarations are statically validated. v0.9.3 adds main-sourced, stale-state
protected environment Promotion PRs that retain the exact image digest and
source commit while changing only the target release file. v0.9.4 requires a
reviewed, unexpired evidence record that matches the current source release,
adds CODEOWNERS and target-environment approvals, and generalizes rollback to
aws-dev, aws-test, and aws-prod. v0.9.5 adds test/prod ALB canary declarations,
Argo Rollouts, release-bound AnalysisRuns, local collection of reviewed AWS
runtime evidence, and a dual static/runtime Promotion gate. v0.9.6 adds the
guarded clean-room aws-test lifecycle, recovery drill sequence, cost-residual
audit, and final evidence contract. The live sequence completed aws-dev and
aws-test validation plus the governed aws-test to aws-prod Promotion, while
aws-prod remained statically validated by design. v0.9.7 defaults disposable
dev/test control-plane ingestion off, provides an explicit all-five-log
production-parity checkpoint, preserves the live profile during management-IP
updates, and ignores only terminal or expired Instant Fleet history after
exact cost-resource checks pass. v0.9.8 closes the manual-operability
documentation gap with a single release procedure that distinguishes GitHub
workflow run IDs from UTC runtime-evidence IDs, corrects the Promotion input
name, and documents how a destroyed aws-test cluster can remain a valid source
for time-bounded static production Promotion.
v0.10.0 converts that validated manual procedure into a machine-readable
application contract and release-state schema. It fixes the only successful
phase path, treats absent environments and unavailable runtime executors as
resumable waits, preserves manual production approval and merge, and includes
offline negative tests for unsafe policy mutations. Workflow implementation,
OIDC/IAM/RBAC, and live runtime orchestration remain later v0.10 increments.
v0.10.1 adds `workflow_call` interfaces to the four existing delivery
workflows, publishes stable stage outputs, and records their script primitives,
mutation scopes, allowed environments, and security boundary in
`delivery/contracts/demo-api-stages.json`. It preserves all v0.9 dispatch and
push paths and does not introduce an orchestrator, automatic merge, or cluster
access.
v0.10.2 introduces `.github/workflows/demo-api-release-orchestrator.yaml`, a
read-only fact collector, and a deterministic planner. The orchestrator derives
one state and recommendation from current release files, matching evidence,
open PR contents, environment availability, and protected-main freshness. Its
workflow artifacts are diagnostic observations rather than mutable release
state. Actual stage dispatch remains deferred to v0.10.4 through v0.10.6, after
the v0.10.3 trusted runtime boundary exists.
v0.10.3 adds `.github/workflows/demo-api-runtime-qualification.yaml`, the
runtime executor/result contracts, short-lived OIDC access, GitOps-managed
read-only Roles, and deterministic runtime collection. The v0.10.8 clean-room
repair separates persistent account-bootstrap runtime IAM roles from
environment-owned EKS access entries, so an absent disposable environment is
distinguished from OIDC failure before cluster creation. An unavailable runner
or absent environment remains a safe wait; no GitHub-hosted fallback or
automatic Terraform apply is allowed.
The temporary runtime result becomes unified qualification evidence in
v0.10.4.
v0.10.4 adds deterministic qualification-scope hashing, same-run artifact
binding, a reviewed append-only aws-dev Bundle, and the single authorized
`qualify-aws-dev` orchestrator action. The explicit repository variable keeps
the action disabled while disposable AWS environments and ephemeral runners
are absent. After the Bundle merges, the planner recommends test Promotion but
does not dispatch it.
v0.10.5 activates that reviewed dev-to-test PR preparation behind
`DEMO_API_AWS_TEST_PROMOTION_ENABLED`, retains the existing guarded Canary
completion helper, and gates aws-test qualification separately with
`DEMO_API_AWS_TEST_QUALIFICATION_ENABLED`. Both automated paths accept only
protected-main facts; no PR is merged automatically.
v0.10.6 activates reviewed test-to-prod PR preparation behind
`DEMO_API_AWS_PROD_PROMOTION_ENABLED`. The job consumes only the current fresh
aws-test Qualification Bundle, enters the protected `aws-prod` Environment,
and may change only the aws-prod release values file. Production runtime access,
cluster creation, Kubernetes writes, rollback, and automatic merge remain
forbidden.
v0.10.7 adds secret-free short-retention Attempt artifacts, exact new-run retry
lineage, source-ancestry Release supersede, `fresh/expiring/expired/scope_drift/
release_drift/invalid` Bundle states, a one-hour Promotion validity floor, and
an optional manual dev/test rollback handoff. `status` can no longer dispatch
even when activation variables are enabled. All PR closure, merge, rollback,
Kubernetes mutation, environment creation, and production runtime operations
remain human or explicitly out of scope.
v0.10.8 adds `docs/V0.10_FINAL_ACCEPTANCE_RUNBOOK.md`, a machine-readable final
acceptance contract, strict closure-evidence schema/writer/validator, and an
offline negative gate that rejects unsafe production claims or incomplete
cleanup. Its clean-room repair also documents exact supersede/approval ordering
and Release ID derivation while moving trusted runtime roles into an
independent `runtime-identities` state. Live run IDs, PR numbers, Qualification
Bundles, and cleanup times are recorded later through one reviewed evidence-only
PR. The final tag is created only after that record merges; aws-prod remains
desired-state-only.

## Platform Architecture

```text
                         GitHub Repository

                                  |
                                  v

                               Argo CD

                         GitOps Control Plane

                                  |
                                  v

                      Kubernetes Applications

                                  |
                                  v

                         Application Delivery

                    - Helm
                    - Argo Rollouts


                                  |
                                  v

                          demo-api Workload



                 +----------------+----------------+

                 |                                 |

                 v                                 v


        Local Kubernetes Environment       AWS Kubernetes Environment


                 kind                         Amazon EKS


                  |                               |


          ingress-nginx              AWS Load Balancer
                                     Controller


                  |                               |


          Local Ingress                     AWS ALB
```

Both environments use Git and Argo CD as the desired-state control plane.
The local environment focuses on progressive delivery, while the AWS
environment covers cloud infrastructure, AWS-native application delivery,
dynamic capacity, and the CloudNativePG database control plane.
The diagram shows the aws-dev Deployment path. aws-test and aws-prod replace
the single workload/Service hop with an Argo Rollout, stable/canary Services,
ALB weighted target groups, and a release-bound AnalysisRun.

## Deployment Options

### Local GitOps Environment

Use the local environment for fast iteration, GitOps validation, and
progressive-delivery experiments.

See `docs/LOCAL_DEPLOYMENT.md`.

### AWS EKS Environment

Use the AWS environment for Terraform-managed infrastructure, Amazon EKS,
Argo CD bootstrap, AWS-native ingress, and cloud validation.

See `docs/AWS_EKS_DEPLOYMENT.md`.

## Repository Structure

```text
startup-devops-baseline/
├── .github/
│   └── workflows/
├── apps/
│   └── demo-api/
├── clusters/
│   ├── local/
│   └── aws/
│       ├── base/
│       └── overlays/{dev,test,prod}/
├── infra/
│   └── terraform/aws/
│       ├── modules/
│       └── environments/{dev,test,prod}/
├── docs/
├── delivery/
│   └── contracts/
├── evidence/
│   └── demo-api/
├── examples/
├── platform/
└── scripts/
```

## Documentation

### Architecture

- `docs/ARCHITECTURE.md`
- `docs/AWS_EKS_ARCHITECTURE.md`
- `docs/ENVIRONMENT_MODEL.md`
- `docs/MULTI_ENVIRONMENT_GITOPS_MODEL.md`
- `docs/V0.11_OBSERVABILITY_SRE_DESIGN.md`

### Deployment and Operations

- `docs/MULTI_ENVIRONMENT_RELEASE_RUNBOOK.md`
- `docs/LOCAL_DEPLOYMENT.md`
- `docs/AWS_EKS_DEPLOYMENT.md`
- `docs/AWS_EKS_DESTROY_RUNBOOK.md`
- `docs/AWS_PROGRESSIVE_DELIVERY.md`
- `docs/TROUBLESHOOTING.md`

### GitOps and Delivery

- `docs/RELEASE_ORCHESTRATION_MODEL.md`
- `docs/REUSABLE_DELIVERY_STAGES.md`
- `docs/RELEASE_ORCHESTRATOR.md`
- `docs/CI_IMAGE_WORKFLOW.md`
- `docs/DELIVERY_TRACEABILITY.md`
- `docs/GITOPS_ROLLBACK.md`
- `docs/GITOPS_WORKFLOW.md`
- `docs/PROMOTION_GOVERNANCE.md`
- `docs/V0.7_FINAL_VALIDATION.md`
- `docs/GHCR_IMAGE_WORKFLOW.md`
- `docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md`

### Terraform

- `docs/TERRAFORM_OUTPUTS.md`
- `docs/TERRAFORM_STATE_MANAGEMENT.md`

### Project Evolution

- `CHANGELOG.md`
- `docs/ROADMAP.md`
