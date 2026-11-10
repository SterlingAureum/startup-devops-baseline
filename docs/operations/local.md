# Local lifecycle and GitOps handoff

Use `python3 scripts/ops/cli.py COMMAND --env local`. The previous path
`python3 scripts/ops/local.py COMMAND` delegates to the same kind-only flow.
Install Python 3.10+, PyYAML 6.0.3, Docker, kind, kubectl, Git and Helm.

## Responsibilities and commands

The tool creates kind, installs the pinned Argo CD bootstrap, applies a GitOps
root and checks environment delivery. Argo manages the remaining components
and applications. Workload configuration stays in GitOps, not the CLI inventory.

| Command | Behavior |
| --- | --- |
| `show` | Validate and print selected environment configuration; no tools or writes |
| `doctor` | Check installed tools; no live readiness claim |
| `create` | Create named kind cluster if absent, export connection and wait for nodes |
| `install-argocd` | Install the pinned Argo CD manifest and wait for controllers |
| `deploy` | Fetch/pin GitOps source, render preflight, apply root Application |
| `status` | Show nodes and Argo Applications |
| `verify` | Check nodes, Argo and declared Application convergence; no deployment |
| `connect` | Back up/merge selected shared kubeconfig and switch its context explicitly |
| `destroy` | Delete confirmed kind cluster and its dedicated connection file |
| `up` | Source/render preflight, create, install-argocd, deploy, verify |

`--dry-run` validates configuration/arguments and prints phases. It invokes no
tools, writes no files and does not prove network or runtime readiness. AWS
entries support `show` only; even AWS lifecycle dry-runs are explicitly rejected.

## Inspect before changing an existing cluster

For an already running rehearsal, no deletion or recreation is necessary:

```bash
python3 scripts/ops/cli.py show --env local
python3 scripts/ops/cli.py verify --env local --cluster startup-devops-baseline
python3 scripts/ops/cli.py connect --env local --cluster startup-devops-baseline
kubectl get nodes
```

Use the actual cluster name, and the original fork repository through configuration
or `--repo-url` if different. Standalone verify defaults to the root's deployed
full commit, even if inventory `gitops.revision` names a newer branch. An explicit
`--revision` instead checks that requested target; it never upgrades the cluster.
Verify fetches the target source separately, preserving the deployed root's Helm
inputs so an existing local-image rehearsal need not be rebuilt or redeployed.
Argo's API can omit empty Helm parameter values and false forceString fields.
The verifier restores only those API defaults for rendering/comparison; explicit
nulls or invalid types fail, and real parameter changes remain mismatches.

## Configure and create

The checked-in default is `config/environments.example.yaml`. For personal use:

```bash
mkdir -p ~/.config/startup-devops-baseline
cp config/environments.example.yaml ~/.config/startup-devops-baseline/environments.yaml
```

Edit the local environment's cluster/repository/revision as appropriate, then:

```bash
python3 scripts/ops/cli.py show --config ~/.config/startup-devops-baseline/environments.yaml --env local
python3 scripts/ops/cli.py up --config ~/.config/startup-devops-baseline/environments.yaml --env local --revision YOUR_PUSHED_REF --dry-run
python3 scripts/ops/cli.py up --config ~/.config/startup-devops-baseline/environments.yaml --env local --revision YOUR_PUSHED_REF
```

Replace `YOUR_PUSHED_REF`; do not paste it literally. Commit/push GitOps changes
before selecting them. Lifecycle deploy/up fetch the root from the selected Git
commit and do not use uncommitted working-tree changes or build application code.
Root and same-repository children must pin that commit; parent-chart Git wiring
is specified in inventory, not hardcoded in the operator. The initial adapter
supports the existing single-source Helm app-of-apps root and direct child Apps,
not arbitrary recursive ApplicationSets, multi-source or Kustomize roots.

For a fork, set `gitops.repository` or pass a credential-free `--repo-url`.
Private source access for the operator and Argo must be provisioned separately;
this increment does not configure repository secrets.

Defaults retain kind node v1.30.0, Argo CD v3.5.2 and loopback host ports
8080/8443. This is not a component upgrade. Existing clusters retain their port
mappings; `create` does not recreate them. Lifecycle up/deploy use the images
already declared in GitOps, including the default demo's registry image. They do
not automatically replace it with a local build. Applying a new root to an old
local-image rehearsal can therefore change the selected demo image; start with
verify/connect when you only want to inspect that rehearsal.

## Connection handoff

Whenever connection export succeeds, the tool atomically saves a dedicated file:

```text
~/.kube/startup-devops-baseline/CLUSTER.yaml
```

This file has mode 0600, remains after success/failure, and is refreshed from kind.
Execution still uses a temporary private copy and explicit `kind-CLUSTER` context.
Create/delete receive an isolated KUBECONFIG as well. Only explicit connect writes
the shared user configuration or switches its context.

For debugging without changing the shared configuration:

```bash
kubectl --kubeconfig ~/.kube/startup-devops-baseline/startup-devops-baseline.yaml --context kind-startup-devops-baseline get nodes
```

`connect` targets the single `KUBECONFIG` file if configured, otherwise
`~/.kube/config`. With multiple KUBECONFIG files, select the write target:

```bash
python3 scripts/ops/cli.py connect --cluster startup-devops-baseline --kubeconfig-file ~/.kube/config
```

An explicit target is not a shell environment change; when KUBECONFIG contains
multiple files, use `kubectl --kubeconfig TARGET ...` if another file's
current-context takes precedence.

Connect preserves other named entries, preferences and extensions, makes a 0600
backup, writes atomically, and selects the target kind context. Identical kind
entries can be adopted. Exports recorded by this tool can be updated after a
cluster rebuild. Unowned conflicting entries or manually changed owned entries
are rejected before changing the target. Resolve the conflict or choose another
cluster name/config file; there is no blanket force-overwrite option. Do not run
concurrent writers against the same shared config. Symlink targets are rejected.

## Verification scope and separate demo checks

Lifecycle verify checks nodes, the pinned install's Argo controller workloads,
root/declared child source and destination, requested commit reconciliation,
Synced/Healthy and active Application errors. A paused or unhealthy application
cannot be accepted merely because its resources exist. The tool does not promote
Rollouts or change applications during verification. Direct child Applications
come from the rendered pinned root, so a new application's name need not be added
to Python. It does not probe Services, HTTP routes, application versions or metrics,
and does not prove business correctness or telemetry ingestion.

The previous demo-api source-image and runtime path is now an optional example:

```bash
python3 scripts/examples/demo_api.py up --revision YOUR_PUSHED_REF --dry-run
python3 scripts/examples/demo_api.py verify --cluster startup-devops-baseline
```

Example up/build/deploy retain clean-source equality, source-labelled local
images, kind image load and demo-specific overrides. Example verify retains the
counter string fix and checks the demo Rollout, Pods, HTTP version and exposed
metrics. It requires the local-image rehearsal it was designed for; it is not a
generic application verifier. See [runtime check boundaries](runtime-checks.md).
Old `local.py build` moves to `scripts/examples/demo_api.py build`; local.py
up/deploy/verify now have lifecycle-only semantics. The optional example up is
the deliberate replacement for the old combined demo rehearsal.

## Destroy

```bash
python3 scripts/ops/cli.py destroy --cluster startup-devops-baseline --confirm startup-devops-baseline --dry-run
python3 scripts/ops/cli.py destroy --cluster startup-devops-baseline --confirm startup-devops-baseline
```

This deletes in-cluster data and the dedicated connection file. Docker images,
shared kubeconfig entries/backups and its current-context remain unchanged; switch
away or remove stale shared entries deliberately. No AWS or Terraform command is
invoked. Failures otherwise leave resources and exported connections for debugging;
there is no automatic rollback or full lifecycle retry.
