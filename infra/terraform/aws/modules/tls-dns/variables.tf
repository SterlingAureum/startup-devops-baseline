variable "hosted_zone_name" {
  description = "Existing public Route 53 hosted zone that owns the demo hostname."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.hosted_zone_name))
    error_message = "hosted_zone_name must be a valid DNS zone name without a trailing dot."
  }
}

variable "demo_hostname" {
  description = "Public DNS hostname presented by the demo-api ALB."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.demo_hostname))
    error_message = "demo_hostname must be a valid DNS hostname without a trailing dot."
  }
}

variable "tags" {
  description = "Additional tags applied to the ACM certificate."
  type        = map(string)
  default     = {}
}
