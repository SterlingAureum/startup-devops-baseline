# Terraform Outputs

Run:

```bash
terraform -chdir=infra/terraform/aws/environments/dev output
```

## Network

- `vpc_id`: configured in AWS Load Balancer Controller values.
- `public_subnet_ids`: internet-facing load balancer discovery.
- `private_subnet_ids`: EKS worker-node placement.
- `nat_gateway_ids`: cost and teardown verification.

## EKS

- `eks_cluster_name`: kubeconfig and bootstrap scripts.
- `eks_cluster_endpoint`: Kubernetes API endpoint.
- `eks_cluster_version`: EKS Kubernetes minor version.
- `eks_cluster_security_group_id`: EKS-managed security group.
- `eks_node_group_name`: default On-Demand node group.
- `eks_addon_names`: Terraform-managed EKS add-ons.

## Identity

- `eks_oidc_provider_arn`: IRSA trust provider.
- `aws_load_balancer_controller_role_arn`: read by `bootstrap-eks-argocd.sh` to annotate the controller ServiceAccount.

## Operational Rule

Terraform outputs are not automatically committed to Git. After recreating the VPC, update the controller `vpcId` before Argo CD syncs it.
