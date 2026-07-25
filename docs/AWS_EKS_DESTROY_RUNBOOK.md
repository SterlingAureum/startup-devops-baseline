# AWS EKS Destroy Runbook

## Required Order

```text
Suspend aws-dev Root Application automation
        ↓
Suspend PostgreSQL Application automation
        ↓
Delete PostgreSQL Cluster, PVC, namespace, and StorageClass
        ↓
Wait for the gp3 EBS volume to be released
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
Terraform destroy
```

## Automated Entry Point

```bash
./scripts/destroy-aws-dev.sh
```

The script requires typing `destroy` before continuing.

Do not start a new FIS experiment while destroy is running. If an experiment is
already active, wait for it to reach a terminal state and confirm the targeted
instance has terminated before starting teardown.

The workflow intentionally deletes the PostgreSQL data PVC. Because
`gp3-cnpg` uses reclaim policy `Delete`, its EBS volume is also deleted. v0.6.1
has no backup or restore path, so export any required data before confirming
destroy.

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
PostgreSQL gp3 EBS volume
NAT Gateway
Elastic IP
```

Terraform cannot delete the Karpenter node IAM role while it remains attached
to a generated instance profile. Delete NodePools while the controller is
running, wait until NodeClaims and Karpenter nodes are gone, and then delete the
EC2NodeClass. Keep the controller running until the EC2NodeClass has completed
finalizer cleanup.

Do not delete local Terraform state until destruction completes.

Before Terraform destroy, verify that the PostgreSQL PV is gone and that its
`vol-*` identifier no longer appears in `aws ec2 describe-volumes`. A residual
EBS volume does not block VPC deletion, but it continues to incur cost.
