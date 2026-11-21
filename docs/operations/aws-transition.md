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

Default destroy releases the standard dev PVCs without creating EBS snapshots.
To take crash-consistent snapshots of those volumes and keep the CNPG backup
bucket and the demo DB secret, add `--retain-backups` to both commands.
Snapshot mode requires EC2 snapshot creation, tagging and read permissions.
Previously recorded snapshots are listed and preserved in either mode.

For a fresh dev installation the EKS cluster, CNPG bucket and demo DB secret
receive the same creation-plan tag when created in one Terraform plan. A
normal destroy can remove the two data resources only with a matching marker.
Bucket deletion also requires its stored force_destroy setting and includes
its objects and versions. Secrets Manager uses the resource's configured
recovery window. Legacy, imported without matching markers, or separately
created data resources are retained. Existing tags are not backfilled on
upgrade. Treat the disposable bucket as exclusive to this environment.
The preview lists the data resource names, Terraform addresses, shared state
location and recorded snapshots. Shared state, KMS and persistent runtime
identities belong to separate roots. Retained backups and secrets can incur
charges. Check a retained AWSCURRENT credential before reusing it with a fresh DB.

Destroy pauses Argo application reconciliation and leaves the AWS Load Balancer
Controller running. The operator needs ELBv2 DescribeLoadBalancers and
DescribeTags. Other ELBv2 load balancers in this VPC block teardown before
the first cluster change. The executor requests deletion of the standard demo
Ingress and polls its finalizers and the identified ALB. Every 30 seconds it
reports the ALB ARN, controller availability and latest Ingress warning.
The wait is limited to ten minutes or the shorter environment timeout.
If the wait expires, inspect the controller and bindings:

```bash
export KUBECONFIG="$HOME/.kube/startup-devops-baseline/aws-dev.yaml"
kubectl -n startup-apps describe ingress demo-api
kubectl -n startup-apps get targetgroupbindings.elbv2.k8s.aws
kubectl -n kube-system logs -l app.kubernetes.io/name=aws-load-balancer-controller --all-containers --prefix --since=15m --tail=100
```

After releasing the Ingress, destroy deletes the ExternalSecrets in the dedicated
startup-apps namespace while ESO and its namespaced permissions are available.
The CLI waits for those objects to disappear before deleting namespaces. A
timeout reports remaining names and finalizers so the operator can inspect ESO.

After interruption, rerun the preview and confirmed destroy from the same
workstation. Before invalidating the cleanup checkpoint or resuming Argo, deploy
checks the root Application and its target namespaces. If any are being deleted,
finish cleanup before rebuilding. A later snapshot request
then takes fresh snapshots, including when the volume IDs are unchanged.
Deploy and destroy share a workstation lock. Keep the local receipt under
`~/.local/state/startup-devops-baseline/` for recovery after partial apply.
Completion verifies the EKS cluster and VPC are absent and only the reported
retained addresses remain in the dev state.
