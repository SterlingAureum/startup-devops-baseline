# Current delivery workflow

Five workflows implement delivery checks, image publication, runtime verification
and promotion. Manual rehearsals exercise report handoff and a two-revision kind deployment.
The old
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

### Checked plan and operator intent

After applicable jobs pass, the aggregate shows the version 1 plan in its job
summary. For a main push or manual main check it also uploads
`checked-plan.json` in `delivery-plan-<checks-run-id>-<attempt>` for 30 days.
A PR gets the summary. The plan records the application, repository, checked
Git range, producer, selected checks and environments, and publication intent.
Its `head` identifies the checked checkout. Runtime targets describe the push
route before feature switches. Actual deployment, image digest and runtime
verdicts belong to their respective producers.

The image workflow consumes the successful upstream run's named artifact. It
checks the repository, workflow, event, branch, head, run and attempt before
using the plan. A missing or mismatched plan fails the route. Each main checks
run keeps its own concurrency group; superseded PR checks may still cancel.
Publishing jobs for the same source SHA share a group. A failed or manually
cancelled main check can be retried from that checks run.

| Change | Static application render | Push runtime targets before switches | Automatic test PR after dev acceptance |
| --- | --- | --- | --- |
| Local cluster declaration | local | None | No |
| Standard AWS overlay | Corresponding AWS environment | Same environment | No |
| AWS base | All AWS environments | All AWS environments | No |
| Shared platform or chart template | All environments | All AWS environments | No |
| One environment's release file | That environment | That AWS environment | Only a dev release change |
| App source | All environments | None | No |

Mixed changes take the union of affected targets. Platform static checks still
lint shared charts and render the three standard AWS overlays. Production
runtime always requires its extra switch. An unmapped cluster path gets broad
static coverage without selecting a live target by itself.

For a no-cloud handoff rehearsal, dispatch **delivery checks** on main with
**publish_image** unchecked. The **delivery image** route reads the plan and
shows its producer in the job summary, even with publication disabled. Publish
and propose-dev should skip. A manual check may explicitly request publication
on main; the repository publication switch must also be enabled. A manual
runtime verification defaults to verification only; opt in to a test PR when
selecting dev. The push runtime workflow still classifies its own push range
using the same routing function and can start alongside checks.

Current tooling:

```bash
python3 scripts/checks/repository.py
python3 -m pip install -r scripts/ops/requirements-preflight.txt
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
same digest. Successful dev verification after a dev release-file change can propose test automatically;
manual promotion can also reverify the current source. The human merges the
PR. Canary pauses require the normal explicit operator action; verifiers do
not bypass pauses. A short-lived CI verification report binds the accepted
release and input hashes; historical evidence bundles are not dependencies.

HTTP `/version` fields and the configured Prometheus query remain **demo
adapters**. Live logs/traces acceptance is unimplemented and not reported as
verified. Private ECR, cross-repository promotion and prod live acceptance are
outside this increment.

## Verification report and promotion

Runtime report schema 1 records the application, environment, expected release
(image repository and digest, source commit and build metadata), GitOps revision,
repository, producer job, run ID and original attempt. Observations include the
Argo Application, synced revision, workload identity, deployed image, Pod image
IDs and source annotation. When a Rollout exposes a current hash, its matching
owned AnalysisRun names, UIDs and phases can be attached (up to eight recent
runs). Analysis references provide diagnostic context; absence alone proves
nothing about an analysis result.

The runtime script records passed, failed or superseded. An observed descendant of the requested revision ends the run with a diagnostic. Reverify current main to produce a new promotion report. Successful verification
uploads `delivery-verified-ENV-RUN-ATTEMPT`; a script failure uploads a separate
`delivery-diagnostic-ENV-RUN-ATTEMPT` when the report was written. Preparation
failures, timeouts imposed by the runner, and cancellations can leave only Actions
logs and step outcomes. Artifacts are retained for 30 days.

The reusable verifier exports the successful producer's artifact name. The caller
uses it even when only the proposal job reruns. The PR gate checks the specific
main workflow attempt, exact successful source job, artifact and source input
hashes. A sibling environment may still be pending or have failed. Existing
deployed release files remain valid. Pending PRs with pre-schema or expired
evidence require fresh source verification.

Proposal writers share a concurrency group per target. If GitHub replaces a pending
proposal in that group, reverify the desired current candidate to request it again. A matching open proposal
with valid evidence is reused. A stale matching PR is reported for review and
closure before reproposal. A retry can reuse a pushed branch with the exact
prepared tree. Candidate comparison includes the application, destination and
immutable image. Separate newer images can have their own PR. Required checks
and up-to-date branch protection still apply before human merge.

### Effective GitOps inputs and dev admission

The static gate renders the local root Helm chart or the AWS root Kustomize overlay
and locates the configured child Application. It checks the child's repository,
revision, chart, release name, destination and ordered value files. It renders
the child with its own Helm inputs and compares the cloud workload's image and
annotations to its release. AWS renders need both kubectl and Helm.

A release PR changes one target release file. Put deployment settings such as
replica counts and rollout steps in a separate configuration PR. New dev entries
must match the successful main image publish job and its original
`published.json` receipt, including digest, source commit, run ID and attempt.
A newer application source requires a new publication. Existing deployed
releases can be verified and promoted using current source-environment evidence.
Expired dev receipts require a new publication to admit a pending dev candidate.

The source fingerprint covers the selected environment configuration and values,
its cluster paths (including AWS base), the shared chart, platform files and
delivery logic. The source release has a separate file hash. Each environment's
registered values and release files are excluded from other environments' hashes.
After upgrading from the previous fingerprint, reverify the source before promotion.

### Hosted kind runtime rehearsal

Run **delivery kind rehearsal** manually from main. On one hosted runner, A is
the first parent of the dispatch commit and B is the dispatch commit. Both
revisions must support the current demo chart and image contract. Each image is
built from its own clean checkout and loaded into the same run-specific cluster.
The verifier waits for Argo, the stable Rollout and ready Pods, then checks the
local image, HTTP endpoints and metrics. Once B passes, it checks that the live
verifier rejects A's image identity on B, and separately rejects A's replaced
root. Each negative check requires its specific error.

The artifact `delivery-kind-RUN-ATTEMPT` contains `kind-a.json` and `kind-b.json`
after both verification steps execute. Check `stable_rs`, `pod_image_ids`,
`gitops_revision`, `http_version`, `wrong_image` and `replaced_root`. Wait counts
depend on when the verifier first samples the cluster. Cleanup targets only the
run's kind cluster. AWS credentials and publication switches are unnecessary.
Kind observations use local image IDs and are outside the promotion report allowlist.

### Hosted report handoff rehearsal

On main, run **delivery report rehearsal** with **retry_consumer** checked. The
fixture uploads one synthetic artifact. The consumer downloads it, checks the
specific attempt and successful reusable job using the Actions API, then exits
with the requested rehearsal failure on attempt 1. Select **Re-run failed jobs**.
The consumer should pass with producer attempt 1 and consumer attempt 2 in the
summary. Leaving the input unchecked performs a one-pass handoff. The fixture
is outside the live promotion allowlist and contains no runtime acceptance.

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
