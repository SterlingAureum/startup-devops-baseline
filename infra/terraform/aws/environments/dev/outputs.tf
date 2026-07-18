output "environment_name" {
  description = "Configured environment name."
  value       = var.environment
}

output "cluster_name" {
  description = "Name reserved for the future EKS cluster."
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

output "eks_module_status" {
  description = "Current implementation status of the EKS module."
  value       = module.eks.status
}
