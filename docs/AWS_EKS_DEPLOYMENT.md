# AWS EKS Deployment

## Deployment Flow

```text
Developer
  -> Terraform apply
  -> VPC, EKS control plane, and Managed Node Group
  -> kubeconfig
  -> Argo CD bootstrap
  -> AWS Root Application
  -> sync wave 0: AWS Load Balancer Controller and Karpenter CRDs
  -> sync waves 5-7: Karpenter, cert-manager, CloudNativePG, and Barman
  -> sync waves 10-15: EC2NodeClasses and NodePools
  -> sync wave 20: PostgreSQL HA and backup resources
  -> sync wave 30: demo-api
  -> Kubernetes resources healthy
  -> internet-facing ALB available
```

## Prerequisites

```text
aws
terraform
kubectl
helm
git
curl
jq
```

Confirm identity:

```bash
aws sts get-caller-identity
```

## 1. Prepare Variables

```bash
cp infra/terraform/aws/environments/dev/terraform.tfvars.example \
  infra/terraform/aws/environments/dev/terraform.tfvars
```

Review region, Availability Zones, Kubernetes version, Service CIDR, API CIDRs,
and tags. Keep `eks_service_ipv4_cidr = "172.20.0.0/16"` aligned with the
data-platform NetworkPolicy contract.

## 2. Validate Terraform

```bash
./scripts/validate-terraform.sh
```

## 3. Plan and Apply

```bash
terraform -chdir=infra/terraform/aws/environments/dev init
terraform -chdir=infra/terraform/aws/environments/dev plan -out=tfplan
terraform -chdir=infra/terraform/aws/environments/dev show tfplan
terraform -chdir=infra/terraform/aws/environments/dev apply tfplan
```

Do not apply an old plan after changing Terraform files.

When introducing the explicit Service CIDR to an existing cluster, first
confirm that EKS already reports `172.20.0.0/16`. The Terraform plan must not
replace the cluster; stop and investigate if replacement is proposed.

## 4. Validate EKS

```bash
./scripts/validate-eks-baseline.sh
./scripts/validate-karpenter-foundation.sh
```

## 5. Bootstrap GitOps

```bash
./scripts/bootstrap-eks-argocd.sh
```

The script creates the AWS Load Balancer Controller and Karpenter IRSA
ServiceAccounts, installs Argo CD, reads the current Terraform `vpc_id`, and
applies the rendered AWS Load Balancer Controller Application.

The repository keeps only the `__VPC_ID__` template marker. Do not commit a
real `vpc-*` value.

## 6. Deploy Root Application

Before deploying the AWS environment, ensure that the current `main` branch
contains an approved, digest-pinned demo-api desired state produced by a
Promotion PR or Rollback PR. The normal forward-delivery flow is:

1. GitHub Actions validates the source and publishes a digest-addressed image.
2. The image workflow creates an aws-dev Promotion PR.
3. A human reviews and merges the values-only PR.
4. Argo CD reconciles the approved desired state.

Do not routinely copy an image digest into the values file or push an image
update directly to `main`.

Deploy or refresh the AWS root Application from the approved `main`
desired state:

```bash
REPO_URL=https://github.com/SterlingAureum/startup-devops-baseline.git \
TARGET_REVISION=main \
./scripts/deploy-aws-dev-root-app.sh
```

The deployment script creates and annotates the PostgreSQL ServiceAccount with
the Terraform-managed backup IRSA role, applies or refreshes the AWS root
Application, waits for the CloudNativePG ObjectStore, and patches its live S3
destination from the Terraform-managed backup bucket. It then waits for the
generated `postgresql-baseline-app` credential and synchronizes only its
`fqdn-uri` into `startup-apps/demo-api-postgresql` as `DATABASE_URL`.

The synchronized Secret is runtime state and is not committed to Git. Re-run
the following command only after application credential rotation:

```bash
./scripts/sync-demo-api-postgresql-secret.sh
```

The root Application manages the AWS platform and data-platform components,
including:

- AWS Load Balancer Controller
- Karpenter
- CloudNativePG
- cert-manager
- Barman Cloud plugin
- PostgreSQL HA and backup resources
- demo-api

The PostgreSQL cluster dynamically provisions three On-Demand database nodes,
three root volumes, and three 20Gi gp3 data volumes. Leave the AWS environment
running only when needed to avoid unnecessary EC2 and EBS charges.

## 7. Validate the Baseline

The backup validator requires at least one completed base backup. On a clean
environment, intentionally create and verify one backup first:

```bash
./scripts/run-cloudnative-pg-backup-test.sh
```

Then run the unified non-disruptive baseline validation:

```bash
./scripts/validate-all.sh
```

When diagnosing a specific layer, the corresponding validators can also be
run independently:

```bash
./scripts/validate-cloudnative-pg-backup.sh
./scripts/validate-cloudnative-pg-recovery.sh
./scripts/validate-demo-api-postgresql.sh
```

Manual checks:

```bash
kubectl get nodes
kubectl get applications -n argocd
kubectl get pods -A
kubectl get ingress -n startup-apps
kubectl get ec2nodeclass
kubectl get nodepools,nodeclaims
kubectl get application cloudnative-pg -n argocd
kubectl get pods -n cnpg-system
kubectl get application postgresql-baseline -n argocd
kubectl get cluster,pods,pvc -n data-platform
kubectl get objectstore,scheduledbackup,backup -n data-platform
kubectl get nodepool database-recovery-ondemand
kubectl get storageclass gp3-cnpg
kubectl get secret demo-api-postgresql -n startup-apps
```

All three EC2NodeClasses and all five NodePools should report `Ready=True`. The
interruption validator should confirm that the controller, SQS queue, and Spot
EventBridge rule use the same queue. The FIS validator should confirm the role,
experiment template, and unique EC2 target tag. Three persistent NodeClaims
should belong to `database-ondemand`; the three temporary application NodePools
and `database-recovery-ondemand` should remain idle outside controlled tests.

The CloudNativePG validators should report two healthy operator replicas on two
different `workload=system` nodes and a PostgreSQL topology containing one
primary and two streaming replicas. The database instances should occupy three
different `database-ondemand` nodes, span both Availability Zones, and own
three encrypted 20Gi gp3 volumes. `validate-all.sh` does not restart a database
instance.

The demo-api validator should confirm that both replicas use the minimum
runtime Secret, reach the current primary through `postgresql-baseline-rw`, and
return a sanitized `/db/health` response. It compares credentials without
printing or decoding them.

Changes to the ObjectStore instance-sidecar resources may require a controlled
CloudNativePG rolling restart; see `docs/TROUBLESHOOTING_V0.6.4.md`.

The test forces WAL switches, creates one plugin-based `Backup`, waits for it
to complete, and verifies both base-backup and WAL objects in S3. It does not
delete the PostgreSQL Cluster or restart the primary.

For the v0.7 delivery identity and Git-based rollback validation, see:

- `docs/DELIVERY_TRACEABILITY.md`
- `docs/GITOPS_ROLLBACK.md`
- `docs/V0.7_FINAL_VALIDATION.md`

## 8. Run the PostgreSQL Replica Persistence Test

First run the non-disruptive validator directly when focused database
diagnostics are useful:

```bash
./scripts/validate-cloudnative-pg-persistence.sh
```

Then run the guarded persistence test:

```bash
./scripts/run-cloudnative-pg-persistence-test.sh
```

The script requires typing `restart-replica`. It writes a marker through the
primary, deletes one replica Pod, waits for CloudNativePG to recreate it, and
verifies that the replica reuses the same PVC, PV, and EBS volume. The primary
and second replica remain available. This is not a primary failover test and is
intentionally excluded from `validate-all.sh`.

Expected final output:

```text
CloudNativePG replica recreation and persistent-volume reuse validation passed.
```

## 9. Run the PostgreSQL Recovery and PITR Test

Run the guarded restore drill only after a successful base-backup and WAL
validation:

```bash
./scripts/run-cloudnative-pg-recovery-test.sh
```

Type:

```text
restore-and-cleanup
```

The test writes uniquely named markers to the source database and creates a
new physical base backup. It restores one independent cluster to the latest
archived state, then restores a second cluster to a captured timestamp. The
latest cluster must contain all three markers. The PITR cluster must contain
the base and pre-target markers but exclude the post-target marker.

Both recovery clusters use the existing backup IRSA ServiceAccount and the
isolated `database-recovery-ondemand` NodePool. Each temporary Cluster, PVC,
EBS volume, NodeClaim, and EC2 node is removed before the test completes. The
source Cluster UID and all three source PVC/PV/EBS mappings must remain
unchanged.

This drill incurs temporary On-Demand EC2 and EBS charges and is intentionally
excluded from `validate-all.sh`.

Expected final output:

```text
CloudNativePG latest recovery, PITR, data integrity, and cleanup validation passed.
```

Then confirm the source remains healthy and no recovery resources remain:

```bash
./scripts/validate-cloudnative-pg-recovery.sh
```

## 10. Run the PostgreSQL Primary Failover Test

Run the guarded Pod-level failover drill only after the non-disruptive
validators succeed:

```bash
./scripts/run-cloudnative-pg-failover-test.sh
```

Type:

```text
failover-primary
```

The test writes a committed marker through demo-api, deletes the current
primary Pod, waits for a replica to be promoted, and verifies that the RW
Service and demo-api move to the new primary. It then proves both pre-failover
data preservation and a new post-failover write. The former primary must return
as a replica with its original PVC, PV, and EBS volume.

The script reports observed database promotion and application recovery times.
These are measurements, not production SLOs. The test does not terminate an
EC2 instance or simulate an Availability Zone failure and is intentionally
excluded from `validate-all.sh`.

Expected final output:

```text
CloudNativePG primary failover and demo-api reconnect validation passed.
```

## 11. Run the Controlled Scale Test

The following command creates a temporary workload and one small On-Demand
application node. It validates scale-out, deletes the workload, and waits for
consolidation-driven scale-in:

```bash
./scripts/run-karpenter-scale-test.sh
```

This test can incur a small temporary EC2 and EBS charge. Run it intentionally;
it is not part of `validate-all.sh`.

Expected final output:

```text
Karpenter On-Demand scale-out and scale-in validation passed.
```

After the test:

```bash
kubectl get nodeclaims
kubectl get nodes -l karpenter.sh/nodepool
```

The three database NodeClaims and nodes remain. Confirm only that the temporary
application pool returned to zero:

```bash
kubectl get nodeclaims \
  -l karpenter.sh/nodepool=application-ondemand
kubectl get nodes \
  -l karpenter.sh/nodepool=application-ondemand
```

Both scoped commands should return no resources.

## 12. Run the Controlled Spot Test

The Spot test validates interruption-path readiness, creates one temporary Spot
node, confirms the EC2 purchase option, deletes the workload, and waits for
scale-in:

```bash
./scripts/run-karpenter-spot-test.sh
```

Spot availability is not guaranteed. If compatible capacity is unavailable,
the script prints the pod, NodeClaim, and namespace event diagnostics and exits
without falling back to On-Demand.

This test incurs a small temporary EC2 and EBS charge. It does not synthesize
an interruption warning or terminate the node forcibly. A full interruption
and replacement drill should use AWS Fault Injection Service.

Expected final output:

```text
Karpenter Spot scale-out and scale-in validation passed.
```

## 13. Run the Real AWS FIS Interruption Drill

This drill creates an isolated Spot node and starts a real AWS FIS experiment:

```bash
./scripts/run-karpenter-fis-spot-test.sh
```

The script requires typing `interrupt`. Before starting FIS, it proves that the
experiment tag resolves to exactly the EC2 instance hosting the temporary test
Pod. It then validates a replacement Pod on a different Spot instance,
original-instance termination, NodeClaim removal, and final scale-in.

The interruption cannot be undone after EC2 accepts it. This drill incurs
temporary EC2, EBS, and AWS FIS charges and is not part of
`validate-all.sh`.

Expected final output:

```text
Karpenter AWS FIS Spot interruption and replacement validation passed.
```

## 14. Destroy

Review `docs/AWS_EKS_DESTROY_RUNBOOK.md` before destroying the environment.
The destroy script removes Kubernetes-managed AWS resources before Terraform
destroys the VPC. It also permanently deletes the CloudNativePG S3 bucket,
including base backups, WAL archives, current objects, and noncurrent object
versions.

```bash
./scripts/destroy-aws-dev.sh
```

The script prints the resolved cluster, region, and Terraform directory and
requires the following explicit confirmation:

```text
destroy-with-backups
```

After completion, review AWS for unexpected residual load balancers, NAT
Gateways, Elastic IPs, EC2 instances, and EBS volumes.
