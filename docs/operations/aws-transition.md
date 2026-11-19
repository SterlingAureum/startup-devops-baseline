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

The current AWS lifecycle CLI offers show and offline preflight. An executable provisioning,
bootstrap and teardown path for new clusters is still pending. The workflows for runtime
validation operate on an existing cluster. Leave publication, cloud runtime and prod switches
off for the offline phase. Archived v0.12 executors are historical material.
