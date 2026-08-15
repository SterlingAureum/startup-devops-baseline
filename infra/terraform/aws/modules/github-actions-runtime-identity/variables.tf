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

variable "runtime_role_arn" {
  description = "Persistent account-bootstrap runtime role mapped into the live EKS cluster."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$", var.runtime_role_arn))
    error_message = "runtime_role_arn must identify one IAM role."
  }
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

variable "tags" {
  description = "Additional tags applied to the EKS access entry."
  type        = map(string)
  default     = {}
}
