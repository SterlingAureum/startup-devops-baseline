# Current delivery workflow

Current CI is independent of the archived v0.12 validators. Five
`delivery-*.yaml` workflows are the only active Actions entrypoints. The old
`DELIVERY_FLOW_ENABLED` switch has no effect; disabling a current feature never
restores an old workflow.

## Checks and routing

`delivery checks` starts on PRs, main pushes and manual dispatch. The final
required check is **delivery quality-gates**. It requires the router, current
repository checks/secret scan and unit tests, plus every applicable app test,
render, platform or Terraform job. PRs always check promotion policy. A required
job that is skipped, failed or cancelled cannot pass the aggregate.

`config.json` defines application, IaC, platform and shared tooling paths. Mixed
changes combine checks; unknown code/config paths run the full current checks.
Ordinary documentation and `archive/` changes do not rebuild the app or replay
historical validators. Repository syntax/entrypoint checks, tests and secret
scanning still run. Archives are included in secret scanning.

Operator inventory (`config/`) and optional example helpers (`scripts/examples/`)
are shared tooling inputs. Repository checks validate the environment example
schema without authenticating to AWS. Workflow names and required check names
are unchanged by the lifecycle entrypoint split.

Current tooling:

```bash
python3 scripts/checks/repository.py
python3 -m unittest discover -s tests -v
bash scripts/checks/terraform.sh
python3 scripts/delivery/flow.py render --environment local
python3 scripts/delivery/flow.py platform
```

Helm is required for the local render integration test. Terraform checks cover
five roots with `init -backend=false` and validation, never plan/apply. Platform
checks lint/render repository-owned charts and AWS Kustomize overlays. They do
not download every external controller chart or prove live compatibility.

## Optional cloud jobs

| Variable | Meaning |
| --- | --- |
| `DELIVERY_PUBLISH_ENABLED=true` | Permit image publication after successful main checks and preparation of a dev release PR |
| `DELIVERY_RUNTIME_ENABLED=true` | Permit read-only acceptance against existing trusted runtime runners/clusters and subsequent promotion PR preparation |
| `DELIVERY_PROD_ENABLED=true` | Additionally permit the prod path; keep unset during this restructuring |

All three are unset/disabled by default. Checks run without them. The obsolete
`DELIVERY_FLOW_ENABLED` can be removed from repository settings after migration.

Publication uses GHCR and `DELIVERY_PR_TOKEN` for a bot with narrowly scoped
Contents/Pull requests write access. A GitHub App integration must refresh its
installation tokens; a static short-lived installation token is not a durable
secret. PR creation never approves/merges itself or bypasses main protection.

Runtime jobs use existing labels
`self-hosted, linux, x64, trusted-runtime, aws-dev` or `aws-test` and matching
GitHub Environments `aws-dev-runtime` / `aws-test-runtime`. Supply environment
variables `AWS_RUNTIME_ROLE_ARN`, `AWS_REGION`, `DELIVERY_CLUSTER_NAME`, and
optionally `DELIVERY_APP_URL`. Existing OIDC, EKS Access Entry and namespace
RBAC must be present. Runtime checkout is bound to the caller's current main
SHA. No Terraform administrator identity is used.

The source environment is reverified before proposing the next environment's
same digest. Successful dev verification can propose test automatically;
manual promotion can also reverify the current source. The human merges the
PR. Canary pauses require the normal explicit operator action; verifiers do
not bypass pauses. A short-lived CI verification report binds the accepted
release and input hashes; historical evidence bundles are not dependencies.

HTTP `/version` fields and the configured Prometheus query remain **demo
adapters**. Live logs/traces acceptance is unimplemented and not reported as
verified. Private ECR, cross-repository promotion and prod live acceptance are
outside this increment.

## Repository settings handoff

Push this increment on the current feature branch and observe `delivery
quality-gates`. Require the new check on main and remove superseded legacy
required-check contexts as part of the same transition. Do not merge a branch
whose applicable new checks are incomplete, and do not treat an absent old
workflow as a passed new check. Keep strict up-to-date protection for promotion
PRs. YAML changes alone do not update branch protection or rulesets.

Check current CODEOWNERS enforcement in repository settings. This increment
defines directory rules but does not create reviewers or change account roles.
Publication/runtime enablement is a later operational step after its actual
credentials, cluster access and rehearsal are ready.
