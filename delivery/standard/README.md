# Standard delivery flow: first implementation

This is the first single-repository implementation of the agreed flow. Application source uses protected `main` plus short-lived feature branches. Environments use separate values files, not permanent application branches. Images move by immutable digest; a promotion does not rebuild the image or copy environment settings.

## What changes now

| Entry | Responsibility |
| --- | --- |
| `delivery checks` | Always starts for PRs and main pushes; routes the applicable tests by changed paths and emits one `delivery quality-gates` result. |
| `delivery image` | After successful main checks, builds/scans/publishes the application image and proposes dev. It ignores PR check runs. |
| `delivery runtime` | After effective environment configuration changes, verifies the exact deployment. Successful dev verification proposes test automatically. |
| `delivery promote selected release` | A manual button that reverifies the current dev or test release and proposes the next environment. No manual YAML copying. |
| `delivery verify environment` | Reusable read-only runtime verification on the existing trusted runner and runtime identity. |

The patch does not create AWS resources, change application code, change existing Helm/Kustomize/IaC inputs, migrate state, move evidence, or create a cluster. Existing apply/bootstrap/destroy scripts are retained. Reworking those operational scripts is a separate increment.

## Activation and ownership

New PR/main checks run as soon as these workflow files are present. Publishing and live verification require these repository variables; unset is not enabled:

| Variable | Value / effect |
| --- | --- |
| `DELIVERY_FLOW_ENABLED` | `true` switches to the new publishing flow and skips the old validate, Terraform validate, image-publish and release-orchestrator entry jobs. |
| `DELIVERY_RUNTIME_ENABLED` | `true` enables cluster verification and the subsequent automatic test PR. Leave unset until runners and AWS access are ready. |
| `DELIVERY_PROD_ENABLED` | Leave unset for this first rehearsal. `true` additionally permits production release PR checks, promotion and runtime verification. |

The old workflow files and historical scripts remain available for reference. The switch is deliberately an activation/fallback switch: setting it back to false restores the old entry jobs on their next matching events. It is not a global automation pause. Disable the relevant workflows in GitHub when an actual pause is required.

Configure repository secret `DELIVERY_PR_TOKEN` for a bot identity with Contents read/write and Pull requests read/write on this repository. A GitHub App token must be refreshed by your integration; a static installation token expires and is not a durable secret. A repository-scoped fine-grained PAT is a straightforward initial option. Use an identity distinct from the approving reviewer if a human approval is required. The token creates branches and PRs; it must not bypass protected main. We deliberately do not rely on `GITHUB_TOKEN` to trigger checks for bot-created PRs.

After observing the new check on a feature PR, require **`delivery quality-gates`** on main, require branches to be up to date before merging, and remove superseded legacy required-check contexts when switching. This up-to-date requirement also prevents an old promotion PR from using an outdated source-environment verification after main advances. Protect workflow, delivery policy and production configuration changes with the appropriate reviewers. Merge remains the release approval; this implementation adds no duplicate approval ceremony.

The default adapter publishes to the existing GHCR repository. Confirm the cluster can pull it. Private ECR, cross-repository PR credentials and enterprise account separation are not implemented by this increment.

## Runtime prerequisites

For each enabled environment, retain the existing runner labels:

```text
self-hosted, linux, x64, trusted-runtime, aws-dev
self-hosted, linux, x64, trusted-runtime, aws-test
```

The runner needs `aws`, `kubectl`, Python 3 with PyYAML, network access to the EKS API and application HTTPS endpoint, and the ability to port-forward the internal Prometheus Service. No Docker build runs on the runtime runner.

Use GitHub Environments `aws-dev-runtime` and `aws-test-runtime`, matching the existing OIDC subject design. Configure the following environment variables:

| Variable | Meaning |
| --- | --- |
| `AWS_RUNTIME_ROLE_ARN` | Existing environment-specific OIDC runtime role; no infrastructure administrator role is needed. |
| `AWS_REGION` | Cluster region; workflow fallback is `us-east-1`. |
| `DELIVERY_CLUSTER_NAME` | Exact EKS cluster name; required, never guessed. |
| `DELIVERY_APP_URL` | Optional override for the application's HTTPS base URL. Defaults in config come from the supplied environment profiles. |

The existing runtime role needs `eks:DescribeCluster` and its EKS Access Entry/RBAC mapping. Existing namespace roles already describe Argo Applications, Deployments/Rollouts/Pods, and allow Prometheus port-forwarding in `observability`; verify that they are actually deployed. The script neither grants itself permissions nor applies objects. An isolated kubeconfig is removed on exit.

Runtime verification requires all of the following:

1. The Argo Application is Synced and Healthy at the requested main commit.
2. The expected workload generation is observed, its rollout is complete, and active application Pods are ready at the expected image digest.
3. The adapter's `/version` response identifies the target environment and application version.
4. The adapter's Prometheus query returns a positive result for this environment, version and image digest, joined to a healthy, recent scrape target.

The configured application metric name and `/version` JSON fields belong to the **demo adapter**, not to the general offline validator. Replace these adapters for another application. This first increment checks static OTLP transport declarations when present; it does not query Loki/Tempo or prove live log/trace ingestion. `log_and_trace_live_acceptance: true` is rejected until those backend adapters exist, rather than reported as verified.

The test profile still includes its existing manual Canary pause. Complete that pause using your normal authorized Rollouts operation before verification can succeed. The read-only runtime identity does not promote a Rollout. The verifier waits up to 15 minutes and then fails; it does not bypass a pause or turn a failure into a skip.

## First rehearsal

1. Apply on a feature branch. Run the local tests and real application renders described in `apply.md`. Push the branch and inspect the new check results. Keep live verification disabled.
2. Configure the PR bot credential and new required check, then set `DELIVERY_FLOW_ENABLED=true` as part of the entrypoint switch. Merge this increment after applicable checks pass. Do not run the old publisher/orchestrator concurrently.
3. On main, manually run **delivery checks** once. A successful manual run deliberately checks all scopes and permits the first image build even if no application source changed. Subsequent documentation-only pushes do not publish images.
4. Inspect the generated dev PR. It changes only `values/releases/aws-dev.yaml`. Merge it to authorize dev deployment; Argo CD performs the deployment.
5. Configure runtime prerequisites, set `DELIVERY_RUNTIME_ENABLED=true`, and manually run **delivery runtime** on main for `aws-dev`. If already enabled at step 4, the dev release merge starts it automatically.
6. Successful dev runtime verification creates a test PR. Inspect the identical digest and independent test settings, then merge. Argo deploys test; complete its Canary pause and inspect runtime acceptance.
7. Stop here for the first rehearsal. Production remains disabled and untested.

For a selected promotion, run **delivery promote selected release** on main. Selecting `aws-dev` reverifies its current release and proposes test. Selecting `aws-test` would propose prod only after production is explicitly enabled. Historical arbitrary-version selection is outside this first implementation.

For a failed or stale verification, fix the cause and rerun the current-main runtime/manual promotion workflow. Main may have advanced before Argo caught the requested revision; a stale run must fail rather than certify another revision. Close obsolete PRs explicitly. Reruns do not force-push over pending candidates or merge PRs automatically. If a PR was created but a later workflow step failed, reverify and generate a fresh candidate rather than accepting its incomplete run.

## Small verification report, not historical evidence

A successful runtime job uploads one `verified.json` CI artifact, retained for 30 days. The target release file records only its source environment and verification run/attempt. PR checks obtain the report through GitHub, require a successful main workflow from this repository, and compare its image/source identity and deployment-input hashes. Reports from failed runs, another repository, PR workflows, stale inputs, expired artifacts or another environment are rejected.

This ordinary result prevents a manually typed digest from being treated as a verified test/prod promotion. It introduces no evidence directory, bundle schema registry, lease, signed receipt, state migration record or historical closure gate. Expired reports require a fresh verification.

## Path routing and extension boundaries

`config.json` maps paths to application, IaC, platform and shared delivery checks. A mixed commit runs the union. A release-only update renders that environment without rebuilding the application. Shared chart changes re-render local/dev/test/prod; live checks default to dev/test. Platform checks render repository-owned charts and AWS Kustomize overlays. They do not download and validate the resources of every external platform chart or assert live controller compatibility. IaC checks reuse backend-disabled validation, without plan/apply or AWS state access.

The application test command is an argument list run in its configured directory. The default uses the existing Dockerfile's `test` stage. A replacement application can supply its own command; an empty list explicitly disables the business-test hook. Building/scanning the image, deployment checks and runtime acceptance remain separate.

Offline checks support one Deployment or Rollout, app Services and same-namespace ServiceMonitors with matchLabels. They check workload/pod selectors, readiness handler/port declarations, declared target ports, environment identity, cloud image digest references including init containers, metrics wiring and basic declared OTLP transport. This is not full Kubernetes/CRD schema validation or an instrumentation-code scanner.

Enterprise mapping is: application source/build in the app repository, Terraform in infra, and environment release settings in GitOps. This package implements the single-repository flow only. Splitting repositories later requires repository-local path maps, cross-repository bot credentials and source/artifact identity handling; copying identical paths into every repository is not required. The shipped Docker build and runtime HTTP/metrics adapters target this demo, not every Java/Python/frontend application automatically.

## Validation performed for this package

- 29 focused tests cover path routing, mixed changes, deployment wiring, stale/failed verifications, paused Rollouts, image identity, report origin and a real local-Git promotion branch/PR preparation simulation.
- Actual Helm application rendering and the offline validator pass for local, aws-dev, aws-test and aws-prod. Local rendering honors the parent Application's telemetry parameters.
- Helm lint/render passes for the three repository-owned platform charts. Workflow YAML/local dependencies and embedded Bash syntax were checked.
- Patch application is checked against a fresh copy of the supplied v0.12 archive.

GitHub Actions execution, Docker application/image builds, registry publication/scans/attestations, Terraform validation, AWS Kustomize rendering, AWS permissions and live dev/test/prod acceptance were not run in the packaging environment. Helm was available; Docker, Terraform, kubectl and actionlint were not. A local fixture/test pass is not a completed cloud release rehearsal.

Reference behavior: [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [Argo CD automated sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/), [Argo Rollouts traffic management](https://argoproj.github.io/argo-rollouts/features/traffic-management/).
