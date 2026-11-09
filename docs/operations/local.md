# Local kind workflow

The single entrypoint is `python3 scripts/ops/local.py COMMAND`. Run it from any
directory using its absolute path, or run the examples below from the repository
root. Do not use the archived Shell entrypoints.

## Commands

| Command | Behavior |
| --- | --- |
| `doctor` | Check installed tools; runtime/network readiness is checked during actual commands |
| `create` | Create the named kind cluster if absent and wait for nodes |
| `install-argocd` | Install the pinned Argo CD manifest into that kind cluster |
| `build` | Build or reuse the clean commit's local image and load it into kind |
| `deploy` | Verify pushed source and apply the root Application at that commit |
| `status` | Show nodes and Argo Applications in the named cluster |
| `verify` | Read-only verification of the deployed pinned revision, or an explicitly requested revision |
| `destroy` | Delete only the named kind cluster after exact-name confirmation |
| `up` | Run source preflight, create, install, build, deploy and verify in order |

`--dry-run` validates arguments and prints targets/phases. It runs no commands,
does not resolve Git refs, and is not proof that tools, network or a cluster work.

## First rehearsal

Install Python 3.10+, PyYAML 6.0.3, Docker, kind, kubectl, Git and Helm. Commit and
push this increment before a real GitOps deployment. Argo must be able to read
the chosen HTTPS repository; repository credentials for private forks must be
configured separately in Argo. Do not put credentials in `--repo-url`.

```bash
python3 scripts/ops/local.py doctor
python3 scripts/ops/local.py up --revision feature/restructure --dry-run
python3 scripts/ops/local.py up --revision feature/restructure
```

Substitute your actual pushed branch/tag/SHA. For a fork also pass
`--repo-url https://github.com/OWNER/REPOSITORY.git`. The fetched commit must
equal this clean checkout's HEAD, including the current local chart wiring.
Uncommitted changes are deliberately rejected by build/deploy/up. Standalone
read-only verify fetches and renders its target source separately, so a verifier
fix does not require rebuilding the deployed release.

Defaults preserve the existing `kindest/node:v1.30.0` baseline and use the
`v3.5.2` Argo CD manifest already pinned by the prior EKS bootstrap. This is not
a platform upgrade. `--node-image` and `--argocd-manifest` allow an explicitly
selected replacement; compatibility must be checked before using one. The
real local rehearsal remains necessary for these component combinations.

The cluster defaults to `startup-devops-baseline`. Every Kubernetes command
uses a private temporary kubeconfig obtained from that named kind cluster and
an explicit `kind-CLUSTER` context. Creation/deletion also get a private
`KUBECONFIG`; no fallback to an AWS or workstation context is used.

HTTP/HTTPS host ports default to **127.0.0.1:8080 / 8443**. For a newly created
cluster, `--http-port` / `--https-port` change those mappings. Existing clusters
keep their current port mappings; create does not recreate them. Images remain
in the local Docker store after cluster deletion.

## Image and source identity

The image is `startup-devops-baseline/demo-api:local-COMMIT12`, with an OCI source
commit label. An existing tag with another label is rejected; a matching tag
is reused. Build another source commit or explicitly remove the local Docker
image when deliberately rebuilding the same source. Local images use tags;
cloud promotion continues to use registry digests.

Local parent chart parameters explicitly clear the chart's cloud image digest,
set `pullPolicy: Never`, and supply the local source commit and version. Only
the local-image override path changes. AWS environment/release values remain
unchanged. Deploy loads the image again so a recreated kind cluster has it.

## What verify proves

To resume verification after a verifier error, keep the cluster and run:

```bash
python3 scripts/ops/local.py verify --cluster startup-devops-baseline
```

Without `--revision`, verify reads the root Application's pinned commit from
that named kind cluster. It requires the root repository to match `--repo-url`
(pass the original fork URL if needed). It fetches and checks out the target
source in a temporary directory and renders that commit's local chart, not the
current verifier checkout. A root with a floating branch requires an explicit
`--revision`. The verifier does not execute scripts from the fetched source.

An explicit `verify --revision SHA_OR_REF` remains available to verify a chosen
target. Verify never creates a cluster, installs controllers, builds/loads an
image, deploys a root, promotes a Rollout or deletes resources. It does need
Git/network access to the target source in addition to kind/kubectl/Helm.

Verify checks the root and every rendered child Application for Synced/Healthy,
same-repository reconciliation at the requested commit, expected child source
settings, current demo rollout generation, ready Pods using the local image
and source annotation, `/health`, `/ready`, `/version`, and an exposed request
metric. It does not promote a paused Rollout.

Generation and replica counters accept nonnegative JSON integers or decimal
integer strings. Missing status counters remain zero/unconverged; nulls,
booleans, fractions and invalid strings cannot be accepted as healthy status.

The HTTP checks use the Kubernetes [Service proxy API](https://kubernetes.io/docs/tasks/access-application-cluster/access-cluster-services/)
through the explicit local kubeconfig. This does not validate ingress routing,
Prometheus ingestion, Loki ingestion or Tempo ingestion. Those require their
own acceptance adapters. It also does not assert production HA or durability.

Manual ingress smoke check, after the local path is ready:

```bash
curl -H 'Host: demo-api.local' http://127.0.0.1:8080/version
```

Check the actual hostname and port if you changed the ingress or kind settings.
Failures stop the sequence and leave resources for inspection; there is no
automatic rollback, cleanup or retry of a failed lifecycle command. Verification
polls read-only checks for the bounded `--timeout` (default 900 seconds).

## Delete this local environment

```bash
python3 scripts/ops/local.py destroy --cluster startup-devops-baseline \
  --confirm startup-devops-baseline --dry-run
python3 scripts/ops/local.py destroy --cluster startup-devops-baseline \
  --confirm startup-devops-baseline
```

This deletes that kind cluster, including its in-cluster data. It does not
invoke Terraform, AWS, remote state retirement or a shared cloud teardown.
