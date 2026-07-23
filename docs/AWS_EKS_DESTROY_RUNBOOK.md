# AWS EKS Destroy Runbook

## Required Order

```text
Suspend aws-dev Root Application automation
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

## Manual Checks

```bash
kubectl get applications -n argocd
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
Karpenter-generated IAM instance profile
NAT Gateway
Elastic IP
```

Terraform cannot delete the Karpenter node IAM role while it remains attached
to a generated instance profile. Keep the controller running until every
EC2NodeClass has completed finalizer cleanup.

Do not delete local Terraform state until destruction completes.
