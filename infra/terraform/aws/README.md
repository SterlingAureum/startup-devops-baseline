# AWS Terraform baseline

This directory contains the AWS infrastructure code introduced in v0.4.

## Current scope: v0.4.1

The development environment now creates the network baseline required by EKS:

- one VPC;
- two public and two private subnets across two Availability Zones;
- an Internet Gateway and public routing;
- private route tables;
- NAT Gateway egress for private subnets;
- subnet tags for EKS and AWS load balancer discovery.

The EKS module remains a no-resource skeleton and will be implemented next.

## Cost profile

The development defaults use one shared NAT Gateway. This is less resilient
than one NAT Gateway per Availability Zone, but it keeps the lab cost lower.
NAT Gateway hourly and data-processing charges begin after `terraform apply`.

Set `enable_nat_gateway = false` only for static validation or a deliberately
isolated environment. Future EKS nodes in private subnets will need either NAT
egress or the required VPC endpoints to reach AWS and public registries.

## Validate locally

```bash
./scripts/validate-terraform.sh
```

## Plan the VPC

```bash
cp infra/terraform/aws/environments/dev/terraform.tfvars.example \
  infra/terraform/aws/environments/dev/terraform.tfvars

terraform -chdir=infra/terraform/aws/environments/dev init
terraform -chdir=infra/terraform/aws/environments/dev plan
```

Review the plan before applying. `terraform.tfvars` and Terraform state files
are ignored by Git and must not contain credentials.
