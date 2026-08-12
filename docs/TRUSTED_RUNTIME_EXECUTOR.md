# Trusted Runtime Qualification Executor

v0.10.3 implements the non-production runtime boundary that v0.10.0 reserved
for live AWS and Kubernetes facts. It qualifies one immutable `demo-api`
release in `aws-dev` or `aws-test` from protected `main`, using an ephemeral
self-hosted runner and short-lived GitHub OIDC credentials.

v0.10.4 connects only the `aws-dev` executor to the orchestrator when the
`DEMO_API_AWS_DEV_QUALIFICATION_ENABLED=true` repository variable is present.
The manual entrypoint remains available for diagnostics and aws-test remains
outside automatic dispatch. The temporary aws-dev result is combined with a
same-run static result in a reviewed, durable Qualification Bundle.

v0.10.5 connects `aws-test` only after the release PR is merged, the existing
guarded Canary completion helper has run, the orchestrator is manually resumed
with `test_rollout_gate=reviewed-and-completed`, and
`DEMO_API_AWS_TEST_QUALIFICATION_ENABLED=true`. The executor remains read-only;
it verifies the completed Rollout and matching Successful AnalysisRun rather
than progressing either resource.

v0.10.6 does not add an aws-prod executor. Production PR preparation remains a
GitHub-hosted, no-cloud-access operation that consumes the reviewed aws-test
Bundle; production runtime qualification stays outside this release.

## Trust boundary

The workflow has two jobs:

1. A GitHub-hosted preflight checks that the request came from
   `refs/heads/main`, the supplied control-plane SHA is still current, the
   deterministic Release ID is correct, and the target release file hash has
   not changed. This job has `contents: read` only and no AWS/EKS access.
2. A self-hosted job requires `self-hosted`, `linux`, `x64`,
   `trusted-runtime`, and the exact `aws-dev` or `aws-test` label. It enters
   the matching GitHub Environment, requests a short-lived OIDC token, assumes
   that environment's read role, and performs runtime checks.

The runner must execute only one Job and then unregister. It must not contain
an instance-profile EKS role, long-lived AWS keys, a personal kubeconfig, GHCR
write credentials, or repository write tokens. A trusted workstation already
allowed by the EKS public endpoint or an ephemeral EC2 host with private VPC
connectivity can provide the runner.

There is deliberately no GitHub-hosted fallback. If no matching runner is
online, GitHub keeps the Job queued; GitHub currently fails a self-hosted Job
after a 24-hour queue timeout. During that interval the release remains
`waiting_runtime`. Start a fresh ephemeral runner and use the orchestrator's
`resume` operation after the qualification result exists. The repository does
not add a long-lived administration token merely to query runner inventory.

References:

- <https://docs.github.com/actions/reference/runners/self-hosted-runners>
- <https://docs.github.com/actions/reference/security/oidc>
- <https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html>

## Implemented environments

| Runtime environment | GitHub Environment | Runner label | IAM role output | EKS cluster |
| --- | --- | --- | --- | --- |
| `aws-dev` | `aws-dev-runtime` | `aws-dev` | `github_actions_runtime_role_arn` from dev | `startup-devops-baseline-dev` |
| `aws-test` | `aws-test-runtime` | `aws-test` | `github_actions_runtime_role_arn` from test | `startup-devops-baseline-test` |

`aws-prod` has no runtime Workflow option, Terraform module instance, access
entry, runner label, or RBAC overlay in v0.10.3.

## AWS and Kubernetes authorization

`infra/terraform/aws/modules/github-actions-runtime-identity` creates one
role and access entry per enabled non-production root. Its trust policy accepts
only:

```text
aud = sts.amazonaws.com
sub = repo:SterlingAureum/startup-devops-baseline:environment:<aws-dev-runtime|aws-test-runtime>
```

The IAM policy contains only `sts:GetCallerIdentity` and
`eks:DescribeCluster`; the latter is scoped to the exact environment cluster
ARN. The access entry maps the role to
`demo-api-runtime-qualification`. GitOps-managed Roles bind that group in
`argocd` and `startup-apps` with `get`, `list`, and `watch` only.

The Argo CD Application that installs those bindings is packaged as its own
Kustomize resource directory at
`clusters/aws/base/platform/runtime-qualification-rbac/`. The dev and test
overlays reference that directory; the prod overlay does not. Keeping the
Application outside the shared base preserves production exclusion, while the
directory boundary lets standard Kustomize load restrictions remain enabled.
Direct cross-directory references to an individual YAML file are forbidden.

The workflow explicitly verifies that the identity cannot read Secrets,
create Deployments, or create `pods/exec`. Any unexpectedly permissive answer
produces `failed / rbac_boundary_failed`.

The GitHub OIDC provider is account-level shared infrastructure. The module
accepts its ARN rather than creating duplicate providers in disposable dev and
test Terraform states.

## One-time configuration

Perform this only when live acceptance is scheduled:

1. Create or identify the account-level
   `token.actions.githubusercontent.com` IAM OIDC provider.
2. In the selected dev/test Terraform root, set:

   ```hcl
   enable_github_actions_runtime_identity = true
   github_actions_oidc_provider_arn = "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
   ```

3. Apply that environment through the existing reviewed Terraform procedure.
4. Allow Argo CD to sync the dev/test runtime RBAC overlay.
5. Create `aws-dev-runtime` and/or `aws-test-runtime` GitHub Environments.
   Restrict deployment branches to `main` and set these Environment variables:

   ```text
   AWS_RUNTIME_ROLE_ARN=<matching Terraform output>
   AWS_REGION=us-east-1
   ```

6. Start a single-job ephemeral runner with the common labels plus the exact
   environment label. Do not use a runner attached to the target EKS cluster.

## Qualification checks

The trusted collector verifies:

- current `main`, release-file SHA-256, source commit, digest, and Release ID;
- AWS caller and exact EKS cluster existence;
- EKS endpoint reachability;
- negative RBAC checks;
- Argo CD desired `main`, observed revision, sync, and health;
- Deployment or Rollout convergence;
- matching successful AnalysisRun for `aws-test`;
- release annotations;
- every selected Pod ready and every actual `imageID` digest-matched;
- HTTPS `/health`, `/ready`, and `/version` identity.

For orchestrated qualification it waits passively for at most 900 seconds,
polling every 15 seconds for the exact Argo revision and workload readiness.
The wait does not sync Argo CD or mutate a Deployment, Rollout, or AnalysisRun.

The only uploaded path is:

```text
runtime-qualification/result.json
```

The writer rejects fields named like Secrets, tokens, credentials, passwords,
or kubeconfigs. The artifact is retained for 14 days and is not durable by
itself. v0.10.4 accepts it only from the same orchestrator run and embeds it in
a reviewed aws-dev Qualification Bundle.

## Result semantics

| Status | Reasons | Meaning |
| --- | --- | --- |
| `qualified` | `all_checks_passed` | Runtime matches the immutable release. |
| `blocked` | `environment_absent`, `main_advanced`, `oidc_denied`, `endpoint_unreachable`, `executor_unavailable` | Safe pause; correct the condition and resume. |
| `failed` | `argo_not_converged`, `rollout_unhealthy`, `analysis_failed`, `digest_mismatch`, `https_validation_failed`, `rbac_boundary_failed`, `input_mismatch` | Environment exists but qualification is not acceptable. |

An absent cluster never triggers Terraform. A failed result never promotes or
aborts a Rollout, syncs Argo CD, changes a Secret, commits to Git, or opens a
PR.

## Branch-stage validation

No AWS environment or runner is required for this increment:

```bash
./scripts/validate-trusted-runtime-executor.sh
terraform fmt -check -recursive
./scripts/validate-aws-environment-declarations.sh
./scripts/validate-ci-quality-gates.sh
git status --short
```

The environment declaration validator renders all three AWS overlays with
standard Kustomize load restrictions and confirms runtime RBAC exists only in
dev/test. The full quality gate requires the repository's existing Docker and
Helm toolchain.

The trusted-runtime validator builds each negative-test repository from a
filtered archive. It excludes `.git/`, `.terraform/`, `*.tfstate`,
`*.tfstate.*`, `tfplan`, `*.tfplan`, and real `*.tfvars`/`*.tfvars.json` files.
Each mutation workspace is deleted immediately after validation.
`.terraform.lock.hcl`,
`terraform.tfvars.example`, and tracked Terraform configuration remain in the
fixture. This prevents local provider caches and state from multiplying in
`/tmp`; do not replace the filtered copy with `cp -a`.

## Post-merge live check

Do not run this section from the feature branch. `workflow_dispatch` must
already exist on the default branch, and the runtime request must use current
`main`.

First derive the exact six inputs from `main` and the selected release file.
Then invoke:

```bash
gh workflow run demo-api-runtime-qualification.yaml \
  --ref main \
  -f environment=aws-dev \
  -f release_id="${RELEASE_ID}" \
  -f control_plane_sha="${CONTROL_PLANE_SHA}" \
  -f expected_source_commit="${SOURCE_COMMIT}" \
  -f expected_image_digest="${IMAGE_DIGEST}" \
  -f expected_release_file_sha256="${RELEASE_FILE_SHA256}"
```

Inspect the latest run and download only its result artifact:

```bash
gh run list --workflow demo-api-runtime-qualification.yaml --limit 3
gh run watch
```

Live acceptance must cover an absent disposable environment, a qualified
existing dev/test environment, denied Secret/write/exec access, and automatic
runner unregistration after the Job.
