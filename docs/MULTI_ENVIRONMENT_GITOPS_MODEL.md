# Multi-Environment GitOps Model

Status: Accepted in v0.9.0; governed build-once promotion implemented through v0.9.4

## Purpose

v0.9 evolves the repository from one AWS development environment into a
reviewable, build-once promotion baseline:

```text
source build -> aws-dev -> aws-test -> aws-prod
```

The design proves that the same immutable artifact can cross independent
environment boundaries without copying environment-specific configuration,
credentials, or data.

## Topology Decision

Each AWS environment maps to one independent EKS cluster:

| Environment | EKS cluster | Operational role |
|---|---|---|
| `aws-dev` | `startup-devops-baseline-dev` | Cloud integration and first runtime verification |
| `aws-test` | `startup-devops-baseline-test` | Isolated pre-production and failure-path verification |
| `aws-prod` | `startup-devops-baseline-prod` | Production delivery and governance boundary |

Every cluster runs its own Argo CD and reconciles only its environment's desired
state. v0.9 does not introduce a central multi-cluster Argo CD or ApplicationSet.

The development and test clusters may be created sequentially in the same AWS
account for portfolio validation. The production target remains a separate AWS
account with independently controlled access and state.

## Promotion Contract

Permitted transitions:

```text
build -> aws-dev
aws-dev -> aws-test
aws-test -> aws-prod
```

Rejected transitions:

```text
build -> aws-test
build -> aws-prod
aws-dev -> aws-prod
aws-prod -> aws-test
```

v0.9.3 enforces the transition order and requires the source release to remain
current on `main` throughout PR preparation. v0.9.4 additionally requires a
reviewed, unexpired qualification record on `main` whose environment, workflow
run ID, release SHA-256, image identity, and source/build identity match that
current source release before the next PR may be opened.

## Build Once

Only the initial source build creates an image. Promotion preserves all of the
following fields without mutation:

- image repository;
- immutable `sha256` digest;
- source commit;
- build workflow identity;
- application version and release identity.

aws-test and aws-prod must not rebuild, retag as a substitute for identity, or
resolve a mutable tag to a different digest.

## Configuration and Release Separation

v0.9.1 separates stable environment configuration from the promoted release
record:

```text
apps/demo-api/helm/values/
├── environments/
│   ├── aws-dev.yaml
│   ├── aws-test.yaml
│   └── aws-prod.yaml
└── releases/
    ├── aws-dev.yaml
    ├── aws-test.yaml
    └── aws-prod.yaml
```

Environment files own hostnames, replicas, resource sizing, application mode,
rollout policy, image pull behavior, and environment-local Secret references.
Release files own only the immutable artifact and its delivery identity. A
promotion changes the target release file without copying the source
environment file.

Argo CD and every validation render load the environment file first and the
release file second. The former mixed `values-aws-dev.yaml` is removed so there
is one authoritative owner for every value. The original aws-test and aws-prod
seed identities remain valid only until replaced through the ordered v0.9.3
Promotion PR path. Evidence gates are enforced in v0.9.4 before cross-
environment promotion may create its target release PR.

## Git and Review Model

All active environments are declared on one `main` branch. Long-lived dev,
test, and prod Git branches are not used.

Each promotion:

1. reads the source environment release from `main`;
2. reads a separately reviewed evidence record from `main` and proves it is
   fresh and byte-bound to that source release;
3. validates the source release and proves its immutable GHCR digest exists;
4. enters the target GitHub Environment approval boundary;
5. changes only the target environment release record;
6. opens a CODEOWNERS-protected pull request;
7. lets the target cluster's Argo CD reconcile the merged desired state.

v0.9.3 implements steps 1 through 5 with a fail-closed source snapshot:
the workflow records the current `main` revision, reads the source release from
that revision, and aborts if `main` moves before branch push or PR creation.
Each target environment has its own non-cancelling concurrency group. The
workflow never updates environment configuration, never rebuilds or retags the
artifact, never merges its PR, and never connects to EKS.

v0.9.4 adds a separate manual qualification workflow for aws-dev and aws-test.
After the source GitHub Environment gate is approved, it validates the release
schema, renders the Helm profile, proves the exact digest exists in GHCR, and
opens an evidence-only PR. Evidence is valid for seven days by default and only
while its source release bytes remain unchanged. The promotion workflow takes
the evidence run ID, resolves that reviewed record from `main`, and fails closed
on missing, mismatched, tampered, expired, or non-passing evidence.

The record's qualification mode is intentionally
`static-release-qualification`. It does not claim that an unapplied aws-test or
aws-prod cluster is healthy. v0.9.5 adds ALB, Argo Rollouts, AnalysisRun, and
runtime rollout evidence when those environments enter live validation.

GitHub Actions do not receive Kubernetes or EKS administration credentials and
do not directly apply workload manifests. Production automation must not merge
its own promotion pull request.

`.github/CODEOWNERS` protects release records, evidence, and release-governance
automation. Repository branch protection or a ruleset must require code-owner
review for that file to become enforceable. GitHub Environments named
`aws-dev`, `aws-test`, and `aws-prod` provide workflow approval boundaries;
`aws-prod` must require designated production reviewers and must prevent self-
review. These GitHub settings are external control-plane configuration and
cannot be made effective by repository files alone.

## Isolation Contract

The following resources are environment-local and never promoted with the
application image:

| Boundary | Isolation rule |
|---|---|
| Terraform | Separate environment root and state |
| Kubernetes | Separate EKS cluster and Argo CD |
| Network | Unique VPC and non-overlapping address plan |
| IAM | Environment-specific roles and IRSA trust |
| Secrets | Separate Secrets Manager Secret and ESO resources |
| Database | Separate CloudNativePG cluster and credentials |
| Backup | Separate bucket/prefix, keys, retention, and recovery boundary |
| TLS/DNS | Separate hostname, Route 53 record, and certificate identity |
| Evidence | Separate environment validation record |

Database records and Secret values are not copied by the release workflow.
Any test fixtures or production data migration process is a separate,
explicitly governed concern.

## Target Repository Shape

The accepted direction for later increments is:

```text
clusters/aws/
├── base/
└── overlays/
    ├── dev/
    ├── test/
    └── prod/
```

```text
infra/terraform/aws/environments/
├── dev/
├── test/
└── prod/
```

Shared Kubernetes definitions belong in a reusable base and environment
differences in explicit overlays. Terraform environments use separate roots
and state rather than CLI workspaces as a security boundary.

v0.9.2 implements this structure. The base contains one copy of the shared
controllers, Karpenter capacity policy, CloudNativePG resources, External
Secrets resources, and NetworkPolicy contracts. Each overlay owns only its
cluster identity, release values paths, IRSA/resource discovery names, Secret
path, and environment address ranges.

## Runtime and Cost Strategy

Git contains complete desired state for all three AWS environments by the end
of v0.9, but they do not need to run concurrently:

- aws-dev remains the first required live validation target;
- aws-test is created at least once, exercised, and then destroyed;
- aws-prod is fully rendered and statically validated, while live creation is
  optional for the portfolio v0.9 acceptance;
- teardown validation checks for load balancers, EBS volumes, compute, and
  temporary backup resources that could continue generating cost.

## v0.9.0 Implementation Boundary

v0.9.0 delivers only:

- convergence of active aws-dev repository Applications on `main`;
- a CI contract preventing active feature-branch GitOps revisions;
- the topology, isolation, promotion, lifecycle, and repository design rules;
- completed v0.8 and revised v0.9/v1.0 roadmap state.

It does not create aws-test or aws-prod resources, copy the dev Helm values,
refactor Terraform, change the delivery workflow, or introduce ApplicationSet.

## v0.9.1 Implementation Boundary

v0.9.1 delivers:

- environment/release value pairs for aws-dev, aws-test, and aws-prod;
- unchanged aws-dev rendering through ordered multi-file Helm merge;
- release-only aws-dev image promotion and rollback;
- static schema ownership checks and three-environment Helm rendering;
- release-derived application version metadata.

It does not create aws-test or aws-prod infrastructure, generalize the ordered
promotion workflow, add validation evidence, refactor Terraform or cluster
manifests, or enable AWS progressive delivery.

## v0.9.2 Implementation Boundary

v0.9.2 delivers:

- a reusable AWS Kustomize base and dev/test/prod overlays;
- independent Terraform roots and local state boundaries for all three environments;
- non-overlapping VPC and EKS Service CIDRs;
- unique cluster, Secret, backup, certificate, and hostname identities;
- fail-closed production rules for NAT availability, backup deletion, Secret
  recovery, control-plane log retention, and FIS test resources;
- three-environment Terraform and Kustomize validation without applying AWS resources.

It does not create test or production clusters, introduce remote state,
generalize application promotion, create release evidence, or enable AWS
progressive delivery.

## v0.9.3 Implementation Boundary

v0.9.3 delivers:

- the ordered `aws-dev -> aws-test -> aws-prod` environment state machine while
  retaining build to aws-dev in the existing image workflow;
- source release capture exclusively from `main`;
- exact preservation of repository, tag, digest, application version, source
  commit, source repository, and build workflow identity;
- exact digest-addressed GHCR artifact existence validation;
- target-scoped concurrency and fail-closed stale-main detection;
- target-release-only branches and human-reviewed Promotion PRs;
- local behavior tests for allowed, skipped, reverse, invalid-digest, stale-
  source, and diff-isolation paths.

It does not require source-environment validation evidence, add CODEOWNERS or
GitHub Environment reviewers, generalize rollback, merge PRs, contact EKS, or
create any AWS resources. Those governance additions remain v0.9.4 work.

## v0.9.4 Implementation Boundary

v0.9.4 delivers:

- reviewed, machine-readable aws-dev/aws-test static qualification evidence;
- exact evidence binding to source environment, release bytes, immutable image,
  source commit, build workflow identity, evidence run, actor, and timestamp;
- a default seven-day freshness gate and fail-closed evidence validation;
- target GitHub Environment boundaries and CODEOWNERS-protected release paths;
- aws-dev/aws-test/aws-prod historical target-release-only rollback PRs;
- GHCR existence checks, stale-main rejection, per-environment concurrency,
  and no direct EKS access for rollback;
- local tamper, expiry, isolation, and workflow-governance behavior tests.

It does not create AWS resources, run live canaries, claim source-cluster
health, merge its own PRs, or promote Secrets, databases, Terraform state, or
environment configuration. Runtime progressive-delivery evidence remains
v0.9.5 work.

## Deferred Decisions

The following work belongs to later increments:

- test/prod ALB canary mechanics and AnalysisRun behavior in v0.9.5;
- remote Terraform state bootstrap, full observability, and long-term
  operational readiness in v1.0.

## Non-Goals

v0.9 does not add service mesh, multi-region disaster recovery, three
permanently running portfolio clusters, centralized multi-cluster Argo CD,
ApplicationSet, automatic production merge, Secret or database promotion,
full observability, AI infrastructure, or AIOps.
