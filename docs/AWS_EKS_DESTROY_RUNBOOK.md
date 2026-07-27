# AWS EKS Destroy Runbook

## Required Order

```text
Suspend aws-dev Root Application automation
        ↓
Suspend PostgreSQL Application automation
        ↓
Delete source/recovery PostgreSQL Clusters, all data-platform PVCs,
namespace, and StorageClass
        ↓
Wait for all PostgreSQL gp3 EBS volumes to be released
        ↓
Delete the On-Demand, Spot, and FIS test workloads
        ↓
Delete NodePool
        ↓
Karpenter deletes NodeClaims and EC2 nodes
        ↓
Delete EC2NodeClass
        ↓
Karpenter deletes the generated IAM instance profile
        ↓
Delete aws-dev Root Application
        ↓
Delete child Applications and Ingress
        ↓
AWS Load Balancer Controller deletes ALB resources
        ↓
Confirm ALB is gone
        ↓
Terraform permanently deletes the versioned S3 backup bucket
        ↓
Terraform destroys the remaining AWS infrastructure
```

## Automated Entry Point

```bash
./scripts/destroy-aws-dev.sh
```

The script requires typing `destroy-with-backups` before continuing.

Do not start a new FIS experiment while destroy is running. If an experiment is
already active, wait for it to reach a terminal state and confirm the targeted
instance has terminated before starting teardown.

The workflow intentionally deletes all PostgreSQL data PVCs. Because
`gp3-cnpg` uses reclaim policy `Delete`, the three source data EBS volumes and
any residual recovery volume are also deleted. The aws-dev S3 bucket uses
`force_destroy=true`; Terraform destroy
permanently removes all base backups, WAL archives, delete markers, and
noncurrent versions. Copy required backups to storage outside this Terraform
environment before confirming destruction.

## Manual Checks

```bash
kubectl get applications -n argocd
kubectl get clusters.postgresql.cnpg.io -A
kubectl get pvc -n data-platform
kubectl get pv
kubectl get storageclass gp3-cnpg
kubectl get nodepools,nodeclaims
kubectl get nodes -l karpenter.sh/nodepool
kubectl get ec2nodeclass
kubectl get ingress -A
kubectl get service -A
aws elbv2 describe-load-balancers --region us-east-1
terraform -chdir=infra/terraform/aws/environments/dev output -raw cnpg_backup_bucket_name
```

Then:

```bash
terraform -chdir=infra/terraform/aws/environments/dev destroy
```

## Residual Resources

Common dependencies that can block VPC deletion:

```text
Application Load Balancer
Target Group
Load Balancer security group
Elastic network interface
Karpenter-provisioned EC2 node
Karpenter-generated IAM instance profile
PostgreSQL gp3 EBS data volumes
CloudNativePG S3 backup bucket
NAT Gateway
Elastic IP
```

Terraform cannot delete the Karpenter node IAM role while it remains attached
to a generated instance profile. Delete NodePools while the controller is
running, wait until NodeClaims and Karpenter nodes are gone, and then delete the
EC2NodeClass. Keep the controller running until the EC2NodeClass has completed
finalizer cleanup.

Do not delete local Terraform state until destruction completes.

Before Terraform destroy, verify that all PostgreSQL PVs are gone and that
their `vol-*` identifiers no longer appear in `aws ec2 describe-volumes`.
Residual EBS volumes do not block VPC deletion, but they continue to incur
cost.
