variable "project_name" {
  description = "Project name used for backup resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name used for backup resource naming."
  type        = string
}

variable "aws_region" {
  description = "AWS region containing the EKS cluster and backup bucket."
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

variable "force_destroy" {
  description = "Allow Terraform to delete all backup objects with the development bucket."
  type        = bool
  default     = true
}

variable "noncurrent_version_expiration_days" {
  description = "Days to retain noncurrent S3 object versions in the development bucket."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_expiration_days >= 1
    error_message = "noncurrent_version_expiration_days must be at least 1."
  }
}

variable "tags" {
  description = "Additional tags applied to backup resources."
  type        = map(string)
  default     = {}
}
