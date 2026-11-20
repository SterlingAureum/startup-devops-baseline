# Personal AWS dev/test preparation

Run this step before scheduling an EKS session. Start with the repository examples.
Use Python 3.10+, kubectl with built-in Kustomize, and the dependencies below.

```bash
python3 -m pip install -r scripts/ops/requirements-preflight.txt
python3 scripts/ops/cli.py preflight --env aws-dev
python3 scripts/ops/cli.py preflight --env aws-test
```

A zero exit code with `scope: repository-examples` validates the selected Terraform
root, example backend key, cluster/region/hostname wiring, rendered GitOps overlay,
bootstrap VPC placeholder, declared runtime RBAC, runner labels and GitHub Environment.
The example intentionally reports `runtime_access_requested: false`. Each result includes
`live_checks: pending`. The command reads files and invokes local `kubectl kustomize`.
The existing Terraform validate job checks provider schemas. The existing render job
checks the effective application chart and release identity.

### State ownership before 4B

The dev root declares an S3 backend. The test and runtime-identities roots currently
use local state despite the presence of example S3 backend files. The test template
report exposes this in `declared_backend` and `live_blockers`. Personal preflight
refuses to treat test's S3 file as effective while its root declares local state.
Before 4C identify any existing test state and decide where it will live. For
runtime-identities, locate the original state and the existing IAM roles before
considering creation. Preserve the persistent roles through dev/test teardown.

## Check personal inputs

Use your inventory outside Git. If starting fresh, copy `config/environments.example.yaml`
there and prepare the files named in the selected environment. Relative input paths
resolve from the inventory's directory. Tilde paths resolve from the operator's home.
Existing personal files may be used directly.

| Input | Preparation for aws-dev |
| --- | --- |
| Inventory | Select the real 12-digit account, region, operator profile or role, and `infra/terraform/aws/environments/dev`. The operator identity and the Actions runtime role serve different purposes. |
| Private backend file | Use the dev values from the retained state-bootstrap output `backend_configuration`. Add `allowed_account_ids` for the expected account as shown in `infra/terraform/aws/backend-config/dev.s3.tfbackend.example`. Check the bucket, KMS key, region, encryption, native lockfile and environment key. |
| Private tfvars | Start from `infra/terraform/aws/environments/dev/terraform.tfvars.example`. Review project, region, DNS and endpoint settings. For a public endpoint supply restricted IPv4 CIDRs through the private file. For a private endpoint confirm the operator and runner have a network path in 4B. |
| Runtime identity | Use the retained runtime-identities output `aws_dev_runtime_role_arn` for `github_actions_runtime_role_arn`. Set `enable_github_actions_runtime_identity = true` in the intended environment file when preparing runtime access. This makes the future environment plan include the EKS access entry. |
| Capacity and retention | Review the reported min/desired/max, NAT and backup settings before any plan. The dev root has a tracked `observability-capacity.auto.tfvars` at 4/4/4. Passing the unedited example as the explicit var-file sets 2/2/3. Check that the chosen capacity fits the platform. |

```bash
python3 scripts/ops/cli.py preflight --env aws-dev \
  --config ~/.config/startup-devops-baseline/environments.yaml --check-inputs
```

A successful personal check reports `scope: personal-files`. A missing file, wrong key
or mismatched target exits nonzero. Templates retain placeholders and cannot establish
personal readiness. The checks compare selected target fields from root variable defaults,
terraform.tfvars, terraform.tfvars.json, then sorted auto files, with the explicitly
selected file last. Shell TF_VAR/CLI overrides, workspace selection, live account
identity, existing state, drift and actual node capacity need separate verification.
The standard personal profile assumes a single account for state and environment
resources. Keep login credentials, secret contents, state and kubeconfig outside Git.

## Handoff for the live session

| Stage | Evidence to obtain in 4B/4C |
| --- | --- |
| Select or provision dev | Confirm the operator's actual account and region and the state bucket/key before using Terraform. Reconcile existing state and cluster ownership first. For a new cluster, review the environment plan and expected charges before apply. Retain state-bootstrap and runtime-identities separately. |
| Bootstrap | From the selected environment outputs match the real cluster name, VPC ID, AWS Load Balancer Controller and Karpenter IRSA roles. Bind the kube-system service accounts, install the reviewed Argo CD version, seed the ALB child with its VPC ID, then apply the selected root. Verify child sync, TLS/DNS and ingress reachability. |
| Verify dev | Register the matching trusted runner and GitHub Environment. Set AWS_REGION, DELIVERY_CLUSTER_NAME and AWS_RUNTIME_ROLE_ARN for that environment. Confirm the actual OIDC subject, EKS access entry and permissions for the reported Kubernetes group. Run the manual dev verification with test proposal disabled and check the observed release and metrics. |
| Promote to test | Prepare test's own inputs and cluster after dev passes. Keep dev available for reverification. Follow the reviewed promotion PR and verify the same digest on test. |
| Clean up | Decide what happens to CNPG objects/backups and secrets first. Release Argo-managed workloads and cloud-controller resources while controllers and permissions are available. Review the destroy plan for the disposable environment root only. After removal, inspect residual load balancers, volumes, NAT/EIPs, logs and backups. Preserve shared state and persistent identities. |

## Deploy or resume the standard stack on provisioned dev

Run from the repository on the workstation with the personal inventory, AWS CLI,
Terraform and kubectl. This uses the dev S3 backend and default workspace. The
operator profile needs access to EKS, Terraform outputs, Secrets Manager and the
demo Route 53 zone. If role_arn is configured, select credentials for that role.
Use the usual preflight Python environment.

```bash
.venv/bin/python scripts/ops/cli.py deploy --env aws-dev --config ~/.config/startup-devops-baseline/environments.yaml
```

The command refreshes `~/.kube/startup-devops-baseline/aws-dev.yaml`, prepares
ServiceAccounts and Grafana, installs Argo CD, seeds the ALB Application, and
applies the root. It reconciles the CNPG backup destination, seeds the demo's
first AWS credential, preserves existing AWSCURRENT, and creates a DNS alias
when absent. The root tracks main and may provision additional EC2 nodes, gp3
volumes and an ALB. Convergence requires the expected Applications to be Synced
and Healthy. Use the separate dev runtime workflow for HTTP and release validation.

After interruption, run the same command again. An existing foreign backup
destination or DNS record requires operator review. To inspect the cluster:

```bash
export KUBECONFIG="$HOME/.kube/startup-devops-baseline/aws-dev.yaml"
kubectl -n argocd get applications
```

Provisioning uses the dev Terraform root. The following destroy entrypoint handles a provisioned standard personal dev stack. AWS test remains
at the preparation stage. Archived v0.12 executors are historical material.

### Destroy the personal dev cluster

Run from the operator workstation after stopping other deploys and runtime jobs.
Use the same private inventory, operator profile and backend as deployment.
Without confirmation this reads AWS, the cluster, and a saved Terraform plan,
then prints planned deletions and retained addresses. The preview requires AWS
read and Terraform backend/lock access. The confirmed invocation generates and
checks its own fresh plan before the first cluster mutation.

```bash
.venv/bin/python scripts/ops/cli.py destroy --env aws-dev --config ~/.config/startup-devops-baseline/environments.yaml
.venv/bin/python scripts/ops/cli.py destroy --env aws-dev --config ~/.config/startup-devops-baseline/environments.yaml --confirm startup-devops-baseline-dev
```

The operation targets the dedicated personal dev cluster, including its
startup-apps, data-platform and observability namespaces. The dev operator
needs EC2 snapshot creation, tagging and read access in addition to existing
cluster, DNS and Terraform teardown permissions. It stops Argo reconciliation,
records crash-consistent EBS snapshots of the standard PVCs, waits for completed
snapshots, removes the matching DNS alias/Ingress, then releases database and
monitoring volumes, Karpenter workers and generated instance profiles. A
completed EBS snapshot preserves blocks at snapshot time. Application-level
restore validation is a separate operation.

The dev state keeps the CNPG S3 bucket and its settings, and the demo Secrets
Manager secret (needed with retained data). Existing S3 lifecycle policies
still apply. Snapshots, retained objects and the secret incur storage/service
charges. State-bootstrap and runtime-identities have separate ownership.
Snapshots are identified in the local receipt under
`~/.local/state/startup-devops-baseline/`. Dev state with these retained
addresses is expected. On a fresh database deployment, check any retained
AWSCURRENT credential against the new database; a rotated or stale value
needs an explicit reconciliation decision.

The executor verifies the saved plan's changes and applies that file only.
Retry the same confirmed command from the same workstation on interruption.
Keep the private inventory and local receipt for partial apply recovery.
Completion checks require the cluster and VPC to be absent and only retained
addresses to remain in the selected state.
