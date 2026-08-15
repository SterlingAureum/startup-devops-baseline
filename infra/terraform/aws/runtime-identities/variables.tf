variable "aws_region" {
  description = "AWS region containing the exact dev/test EKS cluster names."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for deterministic cluster and role names."
  type        = string
  default     = "startup-devops-baseline"
}

variable "github_repository" {
  description = "Exact GitHub repository trusted by the runtime roles."
  type        = string
  default     = "SterlingAureum/startup-devops-baseline"

  validation {
    condition     = var.github_repository == "SterlingAureum/startup-devops-baseline"
    error_message = "This baseline must retain its exact reviewed GitHub repository identity."
  }
}

variable "github_actions_oidc_provider_arn" {
  description = "Existing account-level GitHub Actions OIDC provider ARN."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.github_actions_oidc_provider_arn))
    error_message = "github_actions_oidc_provider_arn must identify the exact GitHub Actions OIDC provider."
  }
}

variable "additional_tags" {
  description = "Additional tags applied to the persistent runtime roles."
  type        = map(string)
  default     = {}
}
