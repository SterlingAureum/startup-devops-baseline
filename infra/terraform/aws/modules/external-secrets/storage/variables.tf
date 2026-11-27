variable "project_name" {
  description = "Project name used for External Secrets resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name used for External Secrets resource naming."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window. Use 0 only for the disposable aws-dev environment."
  type        = number
  default     = 0

  validation {
    condition = (
      var.recovery_window_in_days == 0 ||
      (
        var.recovery_window_in_days >= 7 &&
        var.recovery_window_in_days <= 30
      )
    )
    error_message = "recovery_window_in_days must be 0 or between 7 and 30."
  }
}

variable "tags" {
  description = "Additional tags applied to External Secrets AWS resources."
  type        = map(string)
  default     = {}
}

variable "creation_marker" {
  type = string
}
