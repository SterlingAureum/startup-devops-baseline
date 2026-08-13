# Automated AWS Dev Qualification and Unified Evidence

v0.10.4 activates one bounded action in the demo-api release orchestrator:
`qualify-aws-dev`. After a reviewed aws-dev release-only PR reaches protected
`main`, the orchestrator can produce static qualification, wait for passive
GitOps convergence, run the trusted aws-dev executor, and prepare one reviewed
Qualification Bundle PR.

v0.10.5 preserves this dev flow unchanged, then consumes the reviewed Bundle
through the separately gated test path documented in
`docs/AWS_TEST_AUTOMATED_QUALIFICATION.md`.

It does not build the image again. The existing image-publish Workflow remains
the only image build, scan, SBOM, publication, attestation, and aws-dev release
PR stage.

## Event sequence

```text
source merged to main
  -> image publish, scan, attest
  -> reviewed aws-dev release-only PR
  -> release PR merged to main
  -> orchestrator derives qualify-aws-dev
  -> same-run static qualification artifact
  -> trusted aws-dev runtime qualification artifact
  -> unified Qualification Bundle
  -> reviewed qualification-only PR
  -> Bundle PR merged to main
  -> orchestrator stops at prepare-test-promotion
```

The orchestrator never waits for a PR review inside one long-running run. A PR
merge changes durable Git facts and a later `resume` run derives the next
state.

## Activation

The repository variable below is the explicit execution switch:

```text
DEMO_API_AWS_DEV_QUALIFICATION_ENABLED=true
```

When it is missing or differs from the exact lowercase value `true`, the
orchestrator still derives and reports `qualify-aws-dev` but does not dispatch
the static or runtime Jobs and does not create a Bundle PR.

Enable it only after all of the following are ready:

- the aws-dev EKS cluster exists;
- the v0.10.3 OIDC role, EKS access entry, and dev runtime RBAC are applied;
- the `aws-dev-runtime` GitHub Environment has `AWS_RUNTIME_ROLE_ARN` and
  `AWS_REGION` variables;
- an ephemeral self-hosted runner with `self-hosted`, `linux`, `x64`,
  `trusted-runtime`, and `aws-dev` labels is online;
- protected `main` contains the v0.10.4 workflows.

If the variable is enabled without an online matching runner, the trusted Job
can remain queued because a self-hosted Job cannot execute its own availability
preflight.

## Same-run artifact boundary

The static stage uses `artifact-only` mode. It does not create the legacy
static evidence PR. The static and trusted runtime jobs upload only
`result.json`, using names derived from the current Workflow run and attempt.

The Bundle Workflow downloads artifacts from the current run only. It does not
accept a run ID or GitHub token for cross-run downloads. The writer additionally
requires both embedded results to name the current orchestrator run ID and
attempt, the same protected-main SHA, release-file SHA-256, source commit,
image digest, Release ID, and `aws-dev` environment.

## Qualification Scope

The Bundle is not invalidated merely because its own evidence-only PR advances
`main`. Instead, `delivery/contracts/demo-api-qualification-scope.json`
selects the aws-dev deployment inputs:

- shared Helm chart structure and templates;
- aws-dev environment and release values;
- aws-dev Argo CD Application and overlay;
- startup-apps ExternalSecret and NetworkPolicy declarations;
- runtime qualification RBAC and its dev-only Application.

The calculator sorts every selected path, hashes each file, and produces
`qualificationScopeSha256` with `sha256-path-content-v1`. Evidence, ordinary
documentation, and unrelated environment values are excluded. A change to a
selected deployment input makes the reviewed Bundle stale and returns the
release to `qualify-aws-dev`.

## Bundle identity and path

Durable records use:

```text
evidence/demo-api/qualification/aws-dev/<release-id>/<run-id>-<attempt>.json
```

Each record embeds:

- immutable Release ID, source commit, image tag/digest, build run, and exact
  release-file SHA-256;
- qualification scope contract hash, scope hash, and sorted file/hash list;
- the complete static result and its SHA-256;
- the complete trusted runtime result and its SHA-256;
- Argo revision, workload/AnalysisRun state, Pod `imageID` values, HTTPS checks,
  runner, GitHub Environment, AWS caller, cluster, workflow run, and attempt;
- `recordedAt` and the earlier of static/runtime expiry;
- the protected-main revision and Bundle-creating workflow identity.

The Bundle writer rejects secret-, token-, credential-, password-, and
kubeconfig-like fields. The PR may add only the single computed Bundle path.
It never merges itself.

## Passive convergence

The trusted collector waits at most 900 seconds and polls every 15 seconds for:

1. the exact Argo CD Application revision to become `Synced` and `Healthy`;
2. the Deployment or Rollout to become fully observed and ready;
3. the remaining release, Pod digest, AnalysisRun, and HTTPS checks.

The timeout is shared by Argo and workload convergence. Polling never runs
`argocd app sync`, `kubectl apply`, Rollout promote/abort, Terraform apply, or
any other mutation.

## Results and resume

| Condition | Outcome |
| --- | --- |
| Bundle already fresh | proceed to `test-release / prepare-test-promotion`; v0.10.5 dispatch requires its separate variable |
| Matching Bundle PR open | `waiting_review`; reuse the PR |
| Cluster absent | runtime `blocked / environment_absent`; restore it manually, then resume |
| Endpoint or OIDC unavailable | runtime blocked; correct access and resume |
| Argo/workload/digest/HTTPS check fails | runtime failed; diagnose and resume after correction |
| `main` advances | stale run stops; recompute from current `main` |
| Scope changes after Bundle merge | Bundle becomes stale; run aws-dev qualification again |

Manual resume command:

```bash
gh workflow run demo-api-release-orchestrator.yaml \
  --ref main \
  -f operation=resume \
  -f release_id=<demo-api-release-id> \
  -f policy=reviewed
```

## Preserved boundaries

v0.10.4 does not:

- publish or rebuild an image;
- create, sync, or mutate an EKS environment;
- dispatch aws-dev to aws-test Promotion;
- execute aws-test or aws-prod qualification;
- merge or auto-merge any PR;
- mutate Argo CD, Rollouts, Secrets, databases, or Terraform;
- trigger rollback.

## Offline validation

```bash
./scripts/validate-demo-api-aws-dev-orchestration.sh
./scripts/validate-demo-api-qualification-bundle.sh
./scripts/validate-trusted-runtime-executor.sh
./scripts/validate-demo-api-release-orchestrator.sh
./scripts/validate-ci-quality-gates.sh
terraform fmt -check -recursive
./scripts/validate-aws-environment-declarations.sh
git diff --check
git status --short
```

The full quality gate additionally requires Docker, Helm, Terraform, jq, and
Kustomize or kubectl. Live Workflow acceptance remains a post-merge exercise
after aws-dev and its ephemeral runner are rebuilt.
