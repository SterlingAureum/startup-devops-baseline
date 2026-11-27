variable "project_name" {
  description = "Project name used for backup resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name used for backup resource naming."
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS IAM OIDC provider used by IRSA."
  type        = string
}

variable "oidc_provider_url" {
  description = "Issuer URL of the EKS IAM OIDC provider used by IRSA."
  type        = string
}

variable "service_account_namespace" {
  description = "Namespace of the CloudNativePG cluster ServiceAccount."
  type        = string
  default     = "data-platform"
}

variable "service_account_name" {
  description = "Name of the CloudNativePG cluster ServiceAccount."
  type        = string
  default     = "postgresql-baseline"
}

variable "tags" {
  description = "Additional tags applied to backup resources."
  type        = map(string)
  default     = {}
}

variable "storage_arn" {
  type = string
}
