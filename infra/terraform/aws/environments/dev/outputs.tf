output "environment_name" {
  description = "Configured environment name."
  value       = var.environment
}

output "vpc_module_status" {
  description = "Current implementation status of the VPC module."
  value       = module.vpc.status
}

output "eks_module_status" {
  description = "Current implementation status of the EKS module."
  value       = module.eks.status
}
