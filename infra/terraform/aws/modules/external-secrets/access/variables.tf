variable "project_name" {
  description = "Project name used for External Secrets resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name used for External Secrets resource naming."
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
  description = "Namespace of the External Secrets Operator ServiceAccount."
  type        = string
  default     = "external-secrets"
}

variable "service_account_name" {
  description = "Name of the External Secrets Operator ServiceAccount."
  type        = string
  default     = "external-secrets"
}

variable "tags" {
  description = "Additional tags applied to External Secrets AWS resources."
  type        = map(string)
  default     = {}
}

variable "storage_arn" {
  type = string
}
