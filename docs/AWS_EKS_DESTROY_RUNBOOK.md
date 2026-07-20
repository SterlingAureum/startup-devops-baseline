# AWS EKS Destroy Runbook

## Required Order

```text
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
NAT Gateway
Elastic IP
```

Do not delete local Terraform state until destruction completes.
