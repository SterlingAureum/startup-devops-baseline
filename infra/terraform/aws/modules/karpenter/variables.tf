variable "project_name" {
  description = "Project name used for Karpenter resource naming and tags."
  type        = string
}

variable "environment" {
  description = "Environment name used for Karpenter resource naming and tags."
  type        = string
}

variable "aws_region" {
  description = "AWS region containing the EKS cluster and Karpenter resources."
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster managed by Karpenter."
  type        = string
}

variable "cluster_arn" {
  description = "ARN of the EKS cluster managed by Karpenter."
  type        = string
}

variable "cluster_security_group_id" {
  description = "EKS cluster security group tagged for EC2NodeClass discovery."
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider used by the Karpenter controller IRSA role."
  type        = string
}

variable "oidc_provider_url" {
  description = "Issuer URL of the IAM OIDC provider used by the Karpenter controller."
  type        = string
}

variable "service_account_namespace" {
  description = "Namespace of the Karpenter controller service account."
  type        = string
  default     = "kube-system"
}

variable "service_account_name" {
  description = "Name of the Karpenter controller service account."
  type        = string
  default     = "karpenter"
}

variable "tags" {
  description = "Additional tags applied to supported Karpenter AWS resources."
  type        = map(string)
  default     = {}
}
