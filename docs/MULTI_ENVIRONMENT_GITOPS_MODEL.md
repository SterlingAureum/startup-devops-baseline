# Multi-Environment GitOps Model

Status: Accepted in v0.9.0

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

The source environment must have validation evidence matching its current
release before a later increment may open the next promotion pull request.

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

Later v0.9 increments will separate stable environment configuration from the
promoted release record:

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
rollout policy, and environment-local Secret references. Release files own only
the immutable artifact and its delivery identity. A promotion changes the
target release file without copying the source environment file.

This is a target structure, not a v0.9.0 filesystem migration. v0.9.1 performs
the Helm split and retains compatibility while the transition is validated.

## Git and Review Model

All active environments are declared on one `main` branch. Long-lived dev,
test, and prod Git branches are not used.

Each promotion:

1. reads the source environment release from `main`;
2. validates the source release and evidence;
3. changes only the target environment release record;
4. opens a pull request;
5. relies on repository review and merge controls;
6. lets the target cluster's Argo CD reconcile the merged desired state.

GitHub Actions do not receive Kubernetes or EKS administration credentials and
do not directly apply workload manifests. Production automation must not merge
its own promotion pull request.

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

v0.9.0 records this direction only. It deliberately leaves `clusters/aws-dev/`
in place so the design checkpoint does not mix baseline convergence with a
large manifest migration.

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

## Deferred Decisions

The following work belongs to later increments:

- exact Helm environment/release schema in v0.9.1;
- reusable AWS base, CIDRs, names, and retention profiles in v0.9.2;
- promotion workflow inputs and stale-source protection in v0.9.3;
- evidence format, CODEOWNERS, approvals, and rollback governance in v0.9.4;
- test/prod ALB canary mechanics and AnalysisRun behavior in v0.9.5;
- remote Terraform state bootstrap, full observability, and long-term
  operational readiness in v1.0.

## Non-Goals

v0.9 does not add service mesh, multi-region disaster recovery, three
permanently running portfolio clusters, centralized multi-cluster Argo CD,
ApplicationSet, automatic production merge, Secret or database promotion,
full observability, AI infrastructure, or AIOps.
