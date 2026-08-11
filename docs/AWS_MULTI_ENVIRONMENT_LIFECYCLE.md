# AWS Multi-Environment Clean-Room Lifecycle

This runbook closes v0.9 without requiring three permanently running EKS
clusters. It validates the existing aws-dev environment, creates aws-test from
the reviewed `main` branch, promotes one immutable artifact, exercises runtime
and recovery behavior, destroys aws-test, and proves that the temporary cost
surface is gone. aws-prod remains a statically rendered governance target in
v0.9.

For the complete operator sequence from image publication through runtime and
qualification evidence, ordered dev-to-test and test-to-prod Promotion, GitHub
approval, and safe pause/resume, use `MULTI_ENVIRONMENT_RELEASE_RUNBOOK.md`.
This document remains the infrastructure clean-room and teardown procedure.

## Safety boundary

- Run every live phase from a clean local `main` equal to `origin/main`.
- Keep the EKS public endpoint allowlist runtime-only; never write the current
  public IP to a tracked tfvars file.
- Use the independent `infra/terraform/aws/environments/test` state. Do not use
  Terraform CLI workspaces to represent environments.
- Do not copy Secrets, PostgreSQL data, backups, Terraform state, or runtime
  evidence between environments. Only the immutable application release
  identity moves through promotion.
- The repository destroy entrypoint accepts aws-dev or aws-test and rejects
  aws-prod. Production is not a disposable portfolio environment.
- Never remove the EKS control plane before Kubernetes Ingress and
  LoadBalancer resources have released their AWS resources.

AWS also recommends removing LoadBalancer Services and Ingress resources
before deleting an EKS cluster so their AWS load balancers are released:
<https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html>.

## Acceptance sequence

### 1. Clean source and static preflight

```bash
git switch main
git pull --ff-only
git status --short

./scripts/validate-aws-environment-declarations.sh
./scripts/validate-demo-api-aws-progressive-delivery.sh
./scripts/validate-v0.9-lifecycle-contracts.sh
./scripts/validate-ci-quality-gates.sh
```

`git status --short` must be empty. Do not run a live clean-room test from a
feature branch or from unreviewed files.

### 2. Re-qualify aws-dev

Validate aws-dev and record fresh v0.9.5 runtime evidence from the restricted
EKS endpoint:

```bash
ENVIRONMENT=aws-dev \
EVIDENCE_ACTOR=SterlingAureum \
  ./scripts/record-demo-api-runtime-evidence-aws.sh
```

Commit the generated evidence through a reviewed PR. The normal static release
evidence workflow must also produce a fresh aws-dev qualification record on
`main` before promotion.

### 3. Create ephemeral aws-test

Review the complete Terraform plan. The create mode refuses an existing
Terraform state or existing test cluster. If a previous apply failed after
creating resources, inspect state and use `AWS_TEST_APPLY_MODE=resume` rather
than deleting state or starting another environment.

```bash
CONFIRM_AWS_TEST_APPLY=apply-ephemeral-aws-test \
  ./scripts/apply-aws-test.sh
```

This creates billable EKS, EC2, NAT Gateway, EBS, S3, Secrets Manager,
CloudWatch, ACM, IAM, and networking resources. Keep the test window bounded.

### 4. Bootstrap GitOps

```bash
CONFIRM_AWS_TEST_BOOTSTRAP=bootstrap-ephemeral-aws-test \
  ./scripts/bootstrap-aws-test.sh
```

The bootstrap is restartable. It reuses the environment-specific Terraform
outputs, installs Argo CD, and applies the aws-test root Application from
`main`. It accepts a temporarily Progressing or Suspended demo-api Application
because a reviewed canary may legitimately be paused; it does not claim
runtime qualification at that point.

### 5. Promote the immutable artifact

Use `demo-api-promote-environment` with:

```text
source_environment: aws-dev
target_environment: aws-test
evidence_run_id: <reviewed aws-dev qualification workflow run ID>
runtime_evidence_id: <reviewed aws-dev runtime evidence id>
```

Review and merge the generated release-only PR. Do not edit the aws-test
environment values in that PR.

Watch the live rollout:

```bash
AWS_REGION=us-east-1 \
aws eks update-kubeconfig \
  --name startup-devops-baseline-test

./scripts/rollout-status.sh
kubectl get analysisrun -n startup-apps
```

After reviewing canary Pods, ALB routing, AnalysisRun results, readiness, and
version identity, advance only the explicit manual pause:

```bash
CONFIRM_AWS_TEST_ROLLOUT=promote-reviewed-aws-test \
  ./scripts/complete-aws-test-rollout.sh
```

The helper stops after three unexpected pauses instead of repeatedly forcing
an unknown strategy forward.

### 6. Runtime and recovery validation

```bash
EVIDENCE_ACTOR=SterlingAureum \
  ./scripts/validate-aws-test-runtime.sh
```

Commit the generated aws-test runtime evidence through a reviewed PR. Then run
the controlled CloudNativePG primary-Pod failover drill with the test cluster
identity:

```bash
CLUSTER_NAME=startup-devops-baseline-test \
CONFIRM_POSTGRES_FAILOVER=failover-primary \
  ./scripts/run-cloudnative-pg-failover-test.sh
```

This verifies committed data before and after primary replacement and confirms
that demo-api database access recovers. It does not simulate an Availability
Zone loss.

### 7. Destroy aws-test

Destroy as soon as the runtime evidence and recovery timestamps are safely
recorded:

```bash
CONFIRM_AWS_ENVIRONMENT_DESTROY=destroy-aws-test-with-backups \
  ./scripts/destroy-aws-test.sh
```

The destroy sequence suspends Argo CD automation, removes CloudNativePG and
its PVCs, waits for EBS deletion, deletes Karpenter capacity, removes Route 53
and Ingress resources, waits for load-balancer release, and finally runs the
independent test Terraform destroy.

### 8. Prove cost cleanup

```bash
AWS_ENVIRONMENT=aws-test \
  ./scripts/validate-aws-cost-cleanup.sh
```

The audit checks Terraform state, EKS, VPC, non-terminated EC2, EBS, NAT
Gateways, Elastic IPs, the backup bucket, the EKS log group, ACM certificate,
Route 53 Alias, and currently tagged regional resources. The aws-test Secret
uses a seven-day recovery window: a returned `DeletedDate` is an accepted
tombstone, while an active Secret is a failure. AWS documents `DeletedDate` as
the scheduled deletion date:
<https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/describe-secret.html>.
AWS also states that Secrets marked for deletion are not charged during the
recovery window:
<https://docs.aws.amazon.com/secretsmanager/latest/userguide/manage_delete-secret.html>.

The Resource Groups Tagging API is a secondary sweep, not the only inventory
source, because it returns tagged resources supported by that API. Exact
service checks remain authoritative:
<https://docs.aws.amazon.com/cli/latest/reference/resourcegroupstaggingapi/get-resources.html>.

Karpenter-created Instant Fleet history is classified separately. Fleet state
`deleted`, `deleted_terminating`, or an already-expired `NotFound` response is
accepted after the exact instance and infrastructure checks pass. Active,
unknown, or unclassifiable Fleet state remains a cleanup failure. Do not repeat
`delete-fleets` for terminal history; wait for AWS to expire the record.

If the audit fails, do not mark v0.9 complete. Resolve the named residual and
rerun the audit; do not delete Terraform state to hide it.

### 9. Record final v0.9 evidence

After the cleanup audit passes, create the final record using the actual UTC
timestamps and reviewed evidence paths:

```bash
EVIDENCE_ACTOR=SterlingAureum \
DEV_RUNTIME_EVIDENCE_FILE=evidence/demo-api/runtime/aws-dev/<id>.json \
TEST_RELEASE_EVIDENCE_FILE=evidence/demo-api/aws-test/<run-id>.json \
TEST_RUNTIME_EVIDENCE_FILE=evidence/demo-api/runtime/aws-test/<id>.json \
FAILOVER_COMPLETED_AT=<UTC timestamp> \
TEST_DESTROY_COMPLETED_AT=<UTC timestamp> \
COST_AUDIT_COMPLETED_AT=<UTC timestamp> \
  ./scripts/write-v0.9-final-evidence.sh

EVIDENCE_FILE=evidence/v0.9/final/<id>.json \
  ./scripts/validate-v0.9-final-evidence.sh
```

The final record must be reviewed and merged. It proves the sequential
portfolio lifecycle; it does not claim that aws-prod was created or that the
repository has the full v1.0 observability and remote-state platform.

## Failure recovery

| Failure point | Safe continuation |
|---|---|
| Terraform apply interrupted | Inspect `terraform state list`, then rerun with `AWS_TEST_APPLY_MODE=resume` |
| Workstation IP changes | Rerun the guarded endpoint CIDR script with aws-test `TF_DIR` and cluster overrides |
| Argo CD bootstrap interrupted | Rerun `bootstrap-aws-test.sh`; operations are declarative |
| Rollout AnalysisRun fails | Inspect, abort or roll back; never force a failed analysis forward |
| Destroy blocked by ALB | Restore cluster access, remove Ingress/finalizers through the controller, then rerun destroy |
| Cleanup audit reports residuals | Remove the exact named resource through Terraform/controller ownership, then rerun audit |

Do not respond to a partial failure by deleting local Terraform state,
recreating aws-test under a new name, widening the EKS endpoint to
`0.0.0.0/0`, or manually deleting arbitrary tagged resources.
