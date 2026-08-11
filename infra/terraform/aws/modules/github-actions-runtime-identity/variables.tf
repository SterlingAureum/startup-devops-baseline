variable "project_name" {
  description = "Project name used for environment-isolated role naming."
  type        = string
}

variable "environment" {
  description = "Non-production runtime environment."
  type        = string

  validation {
    condition     = contains(["aws-dev", "aws-test"], var.environment)
    error_message = "Trusted runtime identity is implemented only for aws-dev and aws-test."
  }
}

variable "cluster_name" {
  description = "Exact EKS cluster that accepts this runtime role."
  type        = string
}

variable "cluster_arn" {
  description = "Exact EKS cluster ARN allowed by the IAM policy."
  type        = string
}

variable "github_repository" {
  description = "Exact owner/repository bound into the GitHub OIDC subject."
  type        = string
  default     = "SterlingAureum/startup-devops-baseline"

  validation {
    condition     = var.github_repository == "SterlingAureum/startup-devops-baseline"
    error_message = "This baseline must retain its exact reviewed GitHub repository identity."
  }
}

variable "github_oidc_provider_arn" {
  description = "ARN of the account-level token.actions.githubusercontent.com OIDC provider."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.github_oidc_provider_arn))
    error_message = "github_oidc_provider_arn must identify the exact GitHub Actions OIDC provider."
  }
}

variable "tags" {
  description = "Additional tags applied to runtime identity resources."
  type        = map(string)
  default     = {}
}
