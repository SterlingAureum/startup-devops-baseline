variable "database_mode" {
  type    = string
  default = "cnpg"
  validation {
    condition     = contains(["cnpg", "none"], var.database_mode)
    error_message = "Use cnpg or none."
  }
}

# The lifecycle CLI derives these flags from the selected state on every plan.
variable "retained_database_bucket" {
  type    = bool
  default = false
}

variable "retained_database_secret" {
  type    = bool
  default = false
}

variable "database_creation_marker" {
  type    = string
  default = null
}

locals {
  database_mode    = var.database_mode
  database_enabled = var.database_mode == "cnpg"
}

output "database_mode" {
  value = var.database_mode
}
