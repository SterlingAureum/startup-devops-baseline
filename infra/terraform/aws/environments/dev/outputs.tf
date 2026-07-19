output "environment_name" {
  description = "Configured environment name."
  value       = var.environment
}

output "cluster_name" {
  description = "Configured EKS cluster name."
  value       = local.cluster_name
}

output "vpc_id" {
  description = "ID of the development VPC."
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the development VPC."
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of public subnets used by internet-facing load balancers."
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of private subnets reserved for EKS worker nodes."
  value       = module.vpc.private_subnet_ids
}

output "nat_gateway_ids" {
  description = "IDs of NAT Gateways used by private subnet routes."
  value       = module.vpc.nat_gateway_ids
}

output "eks_cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "Kubernetes API endpoint of the EKS cluster."
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_version" {
  description = "Kubernetes version running on the EKS cluster."
  value       = module.eks.cluster_version
}

output "eks_cluster_security_group_id" {
  description = "EKS-managed cluster security group ID."
  value       = module.eks.cluster_security_group_id
}

output "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN for EKS workload identities."
  value       = module.eks.oidc_provider_arn
}

output "eks_node_group_name" {
  description = "Name of the baseline EKS managed node group."
  value       = module.eks.node_group_name
}

output "eks_addon_names" {
  description = "EKS managed add-ons installed by Terraform."
  value       = module.eks.addon_names
}

output "aws_load_balancer_controller_role_arn" {
  description = "IAM role ARN used by the AWS Load Balancer Controller service account."
  value       = module.eks.aws_load_balancer_controller_role_arn
}
