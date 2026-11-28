variable "aws_region" {
  description = "AWS region for the Terraform state bucket and KMS key."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for deterministic backend resource names and tags."
  type        = string
  default     = "startup-devops-baseline"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state. Supply this through an untracked tfvars file."
  type        = string

  validation {
    condition = (
      length(var.state_bucket_name) >= 3 &&
      length(var.state_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.state_bucket_name)) &&
      !strcontains(var.state_bucket_name, "..") &&
      !strcontains(var.state_bucket_name, ".-") &&
      !strcontains(var.state_bucket_name, "-.") &&
      !can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$", var.state_bucket_name))
    )
    error_message = "state_bucket_name must be a valid globally unique S3 bucket name, not an IPv4 address."
  }
}

variable "state_kms_alias" {
  description = "KMS alias for Terraform state encryption."
  type        = string
  default     = "alias/startup-devops-baseline-terraform-state"

  validation {
    condition     = startswith(var.state_kms_alias, "alias/") && length(var.state_kms_alias) > 6
    error_message = "state_kms_alias must start with alias/ and include a non-empty alias name."
  }
}

variable "additional_tags" {
  description = "Additional non-sensitive tags applied to backend resources."
  type        = map(string)
  default     = {}
}

variable "state_encryption" {
  description = "New installations select sse-s3 in terraform.tfvars.example. Omitted values preserve the managed key on existing installations."
  type        = string
  default     = "managed-kms"

  validation {
    condition     = contains(["sse-s3", "managed-kms", "existing-kms"], var.state_encryption)
    error_message = "Choose sse-s3, managed-kms or existing-kms."
  }
}

variable "existing_kms_key_arn" {
  description = "ARN of the existing KMS key when using existing-kms."
  type        = string
  default     = null

  validation {
    condition = var.state_encryption == "existing-kms" ? can(regex(
      "^arn:[^:]+:kms:${var.aws_region}:[0-9]{12}:key/[A-Za-z0-9-]+$", var.existing_kms_key_arn
    )) : var.existing_kms_key_arn == null
    error_message = "Set a regional KMS key ARN only for existing-kms."
  }
}

variable "state_key_overrides" {
  description = "Optional object paths for the five roots. Used in both IAM policies and backend outputs."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for root, key in var.state_key_overrides :
      contains(["bootstrap", "runtime-identities", "dev", "test", "prod"], root) &&
      try(length(trimspace(key)) > 0 && !startswith(key, "/") && !endswith(key, "/") &&
      !can(regex("[*?]|\\$\\{", key)), false)
    ])
    error_message = "Use known root names and literal object paths without a leading or trailing slash, IAM wildcards or policy variables."
  }
}
