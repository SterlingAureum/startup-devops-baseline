# startup-devops-baseline

A Kubernetes / AWS Terraform reference implementation with Argo CD, a demo
application and a current delivery workflow. This branch is rebuilding operator
entrypoints after v0.12. It does not claim production acceptance.

## Current layout

| Directory | Responsibility |
| --- | --- |
| `infra/terraform/aws/` | Existing modules, five Terraform roots and backend examples |
| `clusters/` | Local and AWS Argo CD / Kustomize environment declarations |
| `platform/` | Platform charts, observability and security declarations |
| `apps/demo-api/` | Demo source, Dockerfile, tests, chart and environment values |
| `scripts/ops/` | Shared lifecycle CLI and kind backend; `local.py` remains a kind-only entrypoint |
| `config/environments.example.yaml` | Environment inventory template; no credentials |
| `scripts/examples/` | Optional demo-specific image and runtime rehearsal |
| `scripts/checks/` | Current source, CI result and Terraform checks |
| `scripts/delivery/`, `delivery/standard/` | Current checks, release PRs and application adapters |
| `tests/` | Tests for current code only |
| `docs/operations/` | Current operator instructions |
| `docs/runbooks/alerts/` | Existing alert runbook paths retained for chart links |
| `archive/v0.12/` | Historical tools, contracts, evidence and documentation |

## Local first

Read [the local workflow](docs/operations/local.md). Its `--dry-run` mode shows
targets and phases without invoking tools:

```bash
python3 scripts/ops/cli.py show --env local
python3 scripts/ops/cli.py up --env local --revision YOUR_PUSHED_REF --dry-run
```

Real `up` requires Docker, kind, kubectl, Helm, Git and Python 3.10+ with PyYAML.
It fetches the selected GitOps revision and pins the root and same-repository
children to that commit. Applications and platform components remain Argo CD's
responsibility; this path does not build application images or probe business
HTTP endpoints. The default GitOps declaration uses its existing registry image.

Commands retain a dedicated debug kubeconfig without changing the shared user
configuration. Explicit `connect` backs up/merges the selected shared config and
switches its context. Existing clusters can start with `verify` then `connect`;
they do not need recreation. See [local operations](docs/operations/local.md)
and [configuration boundaries](docs/operations/environment-config.md).

The optional `scripts/examples/demo_api.py` retains local source-image build and
demo-specific runtime checks. Only this example helper requires a clean checkout
matching the pushed source when building/deploying the demo.

## Current checks

```bash
python3 scripts/checks/repository.py
python3 -m unittest discover -s tests -v
python3 scripts/delivery/flow.py render --environment local
```

With Terraform installed, `bash scripts/checks/terraform.sh` performs formatting
and backend-disabled validation of the five roots. It does not plan, apply,
read remote state or migrate a backend. Provider initialization needs network.

The required GitHub check is **delivery quality-gates**. See
[current CI and delivery](delivery/standard/README.md) before changing repository
rules or enabling publication/runtime jobs.

## AWS and enterprise scope

Terraform and AWS GitOps declarations remain in place. Legacy AWS apply,
bootstrap, recovery and destroy scripts are archived together with their
dependencies; AWS environment entries support configuration inspection only,
and the new AWS operator lifecycle is pending. Do not run archived
scripts from their relocated paths as current procedures. Read
[the AWS transition boundary](docs/operations/aws-transition.md).

The local commands and cloud publication/runtime jobs in this increment have
not been live-rehearsed by the package producer. Enterprise account separation,
private ECR, production storage and prod live acceptance remain later work.

## Historical material

[Archive notes](archive/v0.12/README.md) describe the preserved history.
Historical scripts, evidence, version markers and closure contracts do not gate
current changes. Secret scanning still covers archived tracked files.
