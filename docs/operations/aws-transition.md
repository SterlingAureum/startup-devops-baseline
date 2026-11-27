# Personal AWS dev/test preparation

Run this step before scheduling an EKS session. Start with the repository examples.
Use Python 3.10+, kubectl with built-in Kustomize, and the dependencies below.

```bash
python3 -m pip install -r scripts/ops/requirements-preflight.txt
python3 scripts/ops/cli.py preflight --config config/environments.example.yaml --env aws-dev
python3 scripts/ops/cli.py preflight --config config/environments.example.yaml --env aws-test
```

A zero exit code with `scope: repository-examples` validates the selected Terraform
root, selected backend, cluster/region/hostname wiring, rendered GitOps overlay,
bootstrap VPC placeholder, declared runtime RBAC, runner labels and GitHub Environment.
The example intentionally reports `runtime_access_requested: false`. Each result includes
`live_checks: pending`. The command reads files and invokes local `kubectl kustomize`.
The existing Terraform validate job checks provider schemas. The existing render job
checks the effective application chart and release identity.

### Select an inventory entry

`--config` selects the inventory and `--env` selects an exact key under
`environments`. Set `delivery_environment` explicitly beside `driver` in
each schema-2 inventory entry. For example, a test environment named
`team-a-test` selects `delivery_environment: aws-test`. The CLI reads
that target's `root_manifest` from `delivery/standard/config.json` and checks
that it matches the selected Terraform stage.

```bash
python3 scripts/ops/cli.py show --config /path/to/inventory.yaml --env team-a-test
python3 scripts/ops/cli.py preflight --config /path/to/inventory.yaml --env team-a-test
```

Both commands report `environment: team-a-test` and `delivery_environment: aws-test`.
The standard Terraform root selects the physical infrastructure stage.
Preflight reads the cluster name from the selected Terraform inputs and checks
the overlay against it. The test runner labels and GitHub Environment remain
bound to `aws-test`. Both personal targets support `plan`, `create`, `deploy`, `up` and `destroy`.
`deploy` bootstraps an existing cluster. A confirmed `up` provisions and then deploys. Confirmation uses the physical cluster name.

### Select the state address

The dev root uses S3. Set `terraform.backend.type: s3` and
`terraform.backend.config_file` to the private backend file. When updating a dev
inventory, move the path from `terraform.backend_file` to `terraform.backend.config_file`.

With the default personal inventory, `config_file: aws-dev.tfbackend` resolves
to `~/.config/startup-devops-baseline/aws-dev.tfbackend`. From the repository
root, prepare a first private copy with the following commands. The copy skips
an existing destination.

```bash
python3 scripts/ops/cli.py init-config
cp -nT infra/terraform/aws/backend-config/dev.s3.tfbackend.example \
  "$HOME/.config/startup-devops-baseline/aws-dev.tfbackend"
```

If you selected another inventory or configured another path, use the destination
reported by `show --config FILE --env NAME` under `paths.backend_config_file`.
Set the actual bucket, bucket region and allowed account ID, and check the state key.
For an existing SSE-S3 bucket, leave `kms_key_id` omitted. For an SSE-KMS backend,
set it to the existing key ARN. The project's `state-bootstrap` provisions a KMS-backed
bucket and returns the ARN in `backend_configuration`; keep that value when using its bucket. After preparing
the personal tfvars, run `preflight --env aws-dev --check-inputs` to validate
both files locally.

For a fresh test deployment, use the existing state bucket and the dedicated
key `environments/test/terraform.tfstate`. Set the backend in the **test** entry
of your private inventory. Replace the former local backend block in full.

```yaml
backend:
  type: s3
  config_file: aws-test.tfbackend
```

Prepare the private backend file beside the inventory. Fill in the bucket,
bucket region and allowed account. For SSE-KMS, set the key ARN as for dev. Keep the
test key, encryption and native locking from the template.

```bash
inventory="$HOME/.config/startup-devops-baseline/environments.yaml"
cp -nT infra/terraform/aws/backend-config/test.s3.tfbackend.example \
  "$(dirname "$inventory")/aws-test.tfbackend"
# Fill in the private backend and test tfvars before running these commands.
.venv/bin/python scripts/ops/cli.py preflight --env aws-test --config "$inventory" --check-inputs
.venv/bin/python scripts/ops/cli.py plan --env aws-test --config "$inventory"
```

Preflight validates the files offline. Plan reads the selected S3 key and prints
its address and state status before init. For this fresh start expect `absent`.
An existing snapshot, including one with zero resources, has its own lineage;
the standard plan reopens it. If a fresh state was expected, review that
address before provisioning. Access or KMS failures stop the plan. A missing
key also triggers checks for an existing cluster and VPC.

A previous state under the operator's external state directory can stay there.
If a retired `terraform.tfstate` exists directly in the test Terraform root,
move that specific file to a private location outside the checkout before the
first S3 plan. Confirm its resources are retired first. The CLI uses a temporary
Terraform data directory and initializes with `-reconfigure`. Keep the bucket
and any associated KMS key in place.

After reviewing the test plan, use the cluster name printed by preflight.
With the default project name the infrastructure command is:

```bash
.venv/bin/python scripts/ops/cli.py create --env aws-test --config "$inventory" --confirm startup-devops-baseline-test
```

Without confirmation, `create` previews the changes. A confirmed call makes and
checks a fresh plan, applies it, and saves the dedicated kubeconfig. Look for
`Dedicated kubeconfig:` and copy the following `kubectl ... get nodes` command.
To find the path again, run `show` with the same inventory and environment and
read `paths.kubeconfig`. The file is scoped to your AWS account, region and cluster.
The test cluster incurs AWS charges from creation. You can run `destroy` immediately
after `create`.

### Deploy the test GitOps stack

After `create`, use its printed kubectl command to check the test nodes.
From a checkout matching the merged main configuration, run:

```bash
.venv/bin/python scripts/ops/cli.py deploy --env aws-test --config "$inventory"
```

For a fresh environment the one-command alternative is:

```bash
.venv/bin/python scripts/ops/cli.py up --env aws-test --config "$inventory" --confirm startup-devops-baseline-test
```

Both paths apply `startup-devops-aws-test-root`. Its demo Application uses the
image digest in `apps/demo-api/helm/values/releases/aws-test.yaml` on main. To
qualify a promoted image, check that the reviewed promotion PR has merged and
that this file contains the intended digest.

The personal test profile runs canary updates automatically. It requests 20%
traffic, waits 60 seconds, runs the inline web analysis, then advances through
50% to 100% after successful analysis. The CLI waits for the current workload
generation and its ready replicas. A first installation can go straight to
stable. A subsequent credential refresh can trigger a canary in the same deploy.

For an operator approval step, insert `- pause: {}` after `- setWeight: 50` in
`apps/demo-api/helm/values/environments/aws-test.yaml` and merge the configuration
before deploying. At that step the CLI prints the scoped Argo Rollouts plugin
command for promotion. Review the Rollout and AnalysisRuns before running it.
The environment's top-level `timeout` (seconds, AWS default 1800) bounds the
CLI wait for demo replicas. On expiry, inspect the workload with the printed
commands, resolve the pause or failure, then rerun `deploy` against the same environment.

To inspect the canary from a second terminal, point kubectl at the dedicated
test connection:

```bash
inventory="$HOME/.config/startup-devops-baseline/environments.yaml"
kubeconfig="$(.venv/bin/python scripts/ops/cli.py show --env aws-test --config "$inventory" | jq -er '.paths.kubeconfig')" || exit 1
kubectl --kubeconfig "$kubeconfig" -n startup-apps get rollouts.argoproj.io/demo-api
kubectl --kubeconfig "$kubeconfig" -n startup-apps get analysisruns.argoproj.io
```

After the root and its children are Synced and Healthy, run `delivery runtime`
on main with `environment=aws-test` using the configured test runner to qualify
the live release. A successful deploy reports GitOps convergence.

## Choose or add the personal dev database

Select the database in your private inventory before running `plan`. Existing inventories
default to `cnpg`. To run dev without PostgreSQL, add this field under your dev entry:

```yaml
environments:
  aws-dev:
    database:
      mode: none
    # Keep the existing driver, delivery_environment, aws and terraform fields here.
```

Keep the original dev Terraform root, backend and variable-file settings in the inventory.
The CLI selects the composition. Merge the GitOps files into the branch tracked by the root
Application before deploying. Run these offline checks first:

```bash
.venv/bin/python scripts/ops/cli.py preflight --env aws-dev --config "$inventory" --check-inputs
.venv/bin/python scripts/ops/cli.py up --env aws-dev --config "$inventory" --dry-run
```

| Dev transition | What to expect from plan and up |
| --- | --- |
| Fresh environment, `none` | Base VPC/EKS and shared platform. No CNPG resources, database nodes, backup IAM or database credential. |
| Previous teardown with retained database storage, `none` | Use the same dev root, backend and lineage. The CLI checks the bucket and secret in AWS separately. Terraform can move the addresses of surviving storage and refresh records for missing storage. The application runs without a database. Review any tag updates. |
| Fresh environment, `cnpg` | Full dev stack with PostgreSQL, Barman backups, demo credential and database monitoring. |
| Running `none` environment, select `cnpg` | Run `plan`, then `up` with the physical cluster confirmation. EKS and VPC retain their identities. Database access roles are added and existing storage is reused. |
| Running CNPG environment, select `none` | The lifecycle CLI stops before applying the change. Whole-environment teardown remains available through `destroy`. |

For a retained-only dev state, keep the existing S3 key and run:

```bash
.venv/bin/python scripts/ops/cli.py plan --env aws-dev
```

The plan may show the existing bucket and secret moving to `module.cnpg_backup_storage[0]`
and `module.external_secrets_storage[0]`. Their AWS identities stay the same. The CLI checks
the saved plan for removal, replacement, or recreation of retained storage. Confirm
`up` only after reviewing the plan. Use a Git revision containing the dev GitOps profiles.

When adding PostgreSQL online, Argo first reconciles `clusters/aws/profiles/dev-prepare-database`.
The demo keeps its database-free configuration while CNPG becomes ready and ESO reconciles
the credential. The CLI then selects the full dev overlay and waits for the updated replicas.
A failure during preparation leaves the intermediate root in place. Resolve the reported
cause and rerun `up`. A retained operator-managed secret may require explicit adoption of
its exact current version. Installing CNPG on a rebuilt dev cluster starts a new database
and uses a separate WAL prefix in its backup bucket. Existing configured archive paths
remain in use when redeploying their cluster.

`preflight` reports the selected GitOps profile and the canonical `environments/dev` Terraform root.
The CLI derives retention flags from the selected state and passes them to Terraform.
Use the lifecycle CLI for a state containing retained resources. Feature tags group related
resources. Teardown uses the recorded state, cluster generation and retention policy to decide
ownership. Previously recorded snapshots remain governed by the existing teardown policy.
Test continues to use the full CNPG stack.

## Check personal inputs

Use your inventory outside Git. If starting fresh, run `python3 scripts/ops/cli.py init-config` and prepare the files named in the selected environment. Relative input paths
resolve from the inventory's directory. Tilde paths resolve from the operator's home.
Existing personal files may be used directly.

| Input | Preparation for aws-dev |
| --- | --- |
| Inventory | Select the real 12-digit account, region, operator profile or role, and `infra/terraform/aws/environments/dev`. The operator identity and the Actions runtime role serve different purposes. |
| Private backend file | Use the selected environment from the retained state-bootstrap output `backend_configuration`. Set `allowed_account_ids` to the expected account in the matching S3 template. For SSE-S3 omit `kms_key_id`; for SSE-KMS keep the key ARN. Check the bucket, region, encryption, native lockfile and environment key. |
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
identity, remote state, drift and actual node capacity need live verification.
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

## Rebuild personal AWS dev from the inventory

Start in the repository root on the operator workstation. Use the existing dev
S3 backend and persistent runtime role listed in the inventory. The CLI initializes
the dev Terraform root automatically. The selected profile or role needs the
same provisioning permissions as a direct Terraform apply. The following preview
takes a backend lock during planning and prints Terraform's proposed changes.

```bash
inventory="$HOME/.config/startup-devops-baseline/environments.yaml"
.venv/bin/python scripts/ops/cli.py plan --env aws-dev --config "$inventory"
```

To create the infrastructure and bootstrap the standard GitOps stack in one call:

```bash
.venv/bin/python scripts/ops/cli.py up --env aws-dev --config "$inventory" --confirm startup-devops-baseline-dev
```

Each confirmed invocation makes a fresh saved plan with the selected backend,
default workspace and private variable file. It checks the plan and applies that
same file under the workstation lifecycle lock. A separate preview expires at
command exit. Plan and provider working data use a private temporary directory.
Provisioning ignores shell TF_VAR inputs and rejects TF_CLI_ARGS overrides.
The normal dev root can create or update resources. A delete or replacement,
a same-name cluster outside a creation plan's state, or an unfinished network
teardown recorded for the same VPC stops provisioning before apply.

Use `create` with the same confirmation to finish after saving the cluster connection.
Both commands print the dedicated path. A successful `up` or `deploy` also prints
a ready-to-run kubectl command after GitOps convergence.
Without confirmation, `create` and `up` stop after the preview. `--dry-run`
prints phases offline. After a partial apply, run `plan` again and review the
remaining changes. After a successful apply and a bootstrap failure, resume
with `deploy`. The standard demo credential adoption option also works with
`up`. Runtime qualification remains a separate workflow.

## Deploy or resume the standard stack on provisioned dev

Run from the repository on the workstation with the personal inventory, AWS CLI,
Terraform and kubectl. This uses the dev S3 backend and default workspace. The
operator profile needs access to EKS, Terraform outputs, Secrets Manager and the
demo Route 53 zone. If role_arn is configured, select credentials for that role.
Use the usual preflight Python environment.

```bash
.venv/bin/python scripts/ops/cli.py deploy --env aws-dev --config ~/.config/startup-devops-baseline/environments.yaml
```

The command refreshes the dedicated kubeconfig shown by `show --env aws-dev`, prepares
ServiceAccounts and Grafana, installs Argo CD, seeds the ALB Application, and
applies the root. It reconciles the CNPG backup destination, seeds the demo's
database credential and creates a DNS alias
when absent. The root tracks main and may provision additional EC2 nodes, gp3
volumes and an ALB. Convergence requires the expected Applications to be Synced
and Healthy. Use the separate dev runtime workflow for HTTP and release validation.

Deploy retries the ESO consumer Application once at the failed Git revision when the
webhook Service was missing and now has a ready endpoint. It checks the actual
ESO target value, then updates a Pod template annotation containing the AWS
version ID and waits for the Deployment or Rollout replicas to become ready.

The CLI can update a version carrying its bootstrap or rebuild stage. A manually
written version with a different DATABASE_URL requires its operator to reconcile
it or explicitly transfer that exact version. For the standard disposable demo,
read the current VersionId from the CLI diagnostic and append
`--adopt-demo-secret-version VERSION_ID` to one deploy. Subsequent deploys use
the ordinary command. Other JSON properties are preserved. Rotation-enabled
secrets or a pending rotation block writes.

After interruption, run the same command again. An existing foreign backup
destination or DNS record requires operator review. To inspect the cluster:

```bash
kubeconfig="$(.venv/bin/python scripts/ops/cli.py show --env aws-dev | jq -er '.paths.kubeconfig')" || exit 1
export KUBECONFIG="$kubeconfig"
kubectl -n argocd get applications
```

### Destroy a personal dev or test cluster

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

For test, preview the selected S3 state and check the account, cluster, VPC and retained addresses
before confirming with the physical cluster name printed by the CLI.

```bash
.venv/bin/python scripts/ops/cli.py destroy --env aws-test --config "$inventory"
.venv/bin/python scripts/ops/cli.py destroy --env aws-test --config "$inventory" --confirm startup-devops-baseline-test
```

A cluster with infrastructure only still requires Kubernetes API access to check for workloads
and persistent volumes. The CLI scales down the Argo CD controller when present.

Default destroy releases the standard PVCs without creating EBS snapshots.
To take crash-consistent snapshots of those volumes and keep the CNPG backup
bucket and the demo DB secret, add `--retain-backups` to both commands.
Snapshot mode requires EC2 snapshot creation, tagging and read permissions.
Previously recorded snapshot IDs are historical references; destroy does not verify their current existence.
The private teardown receipt records each newly captured snapshot ID with its source volume,
cluster, region and namespace/PVC. In retention mode it also records the live CNPG ObjectStore
destination (bucket and prefix), database cluster and Barman server name when available.
Destroy neither requests a final CNPG physical backup nor certifies that the archive is restorable.
Use a separate CNPG recovery manifest or restore the chosen EBS snapshot to a volume when
data recovery is required. Ordinary up starts the configured environment.

For a fresh dev or test installation the EKS cluster, CNPG bucket and demo DB secret
receive the same creation-plan tag (`BaselineDevCreationPlan`, the historical key)
when created in one Terraform plan. A normal destroy can remove the two data resources only with a matching marker.
Bucket deletion also requires its stored force_destroy setting and includes
its objects and versions. Secrets Manager uses the resource's configured
recovery window. The test example selects seven days, so a deleted secret name may
be unavailable for an immediate rebuild. For repeated disposable test runs, set
`external_secrets_recovery_window_in_days = 0` before creation if immediate deletion is intended.
Destroy retains unmarked test buckets and secrets from earlier runs, along with
imported or separately created data resources whose ownership markers differ. Existing tags are not
backfilled on upgrade. Treat the disposable bucket as exclusive to this environment.
Destroy checks the physical bucket with GetBucketTagging (expected account owner) and the
secret with DescribeSecret (name and stored ARN). Grant the operator these metadata reads.
The output distinguishes present and kept (including the retention reason), missing in AWS
with stale state addresses, and a secret scheduled for deletion with its date.
When only stale addresses and protected data remain, preview lists the stale addresses.
Confirming that same destroy applies a targeted refresh-only Terraform plan only if its managed
drift exactly matches the missing addresses. This updates state without deleting AWS objects.
Alternatively a dev rebuild in database.mode=none checks both stores before planning: an
absent bucket is omitted and a live secret remains managed. The reviewed create/update plan
must still contain no destructive actions. An authorization error or ambiguous identity
stops the operation. Preview leaves the selected state unchanged. Shared state, KMS and persistent runtime
identities belong to separate roots. Retained backups and secrets can incur
charges.

After Kubernetes cleanup, the CLI applies a checked service destroy plan. It
then inspects the original VPC with EKS absent, releases detached VPC CNI ENIs
whose tagged instance is confirmed terminated, and releases the recorded EKS
cluster security group after checking ownership and attachments. The operator
needs EC2 describe permissions and DeleteNetworkInterface/DeleteSecurityGroup.
The CLI preserves NAT interfaces belonging to Terraform gateways for the final
checked network plan. Review any reported unknown ENI or security group before
resuming. An older receipt without the EKS group ID cannot authorize its deletion.

Destroy pauses Argo application reconciliation and leaves the AWS Load Balancer
Controller running. The operator needs ELBv2 DescribeLoadBalancers and
DescribeTags. Other ELBv2 load balancers in this VPC block teardown before
the first cluster change. The executor requests deletion of the standard demo
Ingress and polls its finalizers and the identified ALB. Every 30 seconds it
reports the ALB ARN, controller availability and latest Ingress warning.
The wait is limited to ten minutes or the shorter environment timeout.
If the wait expires, inspect the controller and bindings:

```bash
kubeconfig="$(.venv/bin/python scripts/ops/cli.py show --env aws-dev | jq -er '.paths.kubeconfig')" || exit 1
export KUBECONFIG="$kubeconfig"
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
retained addresses remain in the selected state.
