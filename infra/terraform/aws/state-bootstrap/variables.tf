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
