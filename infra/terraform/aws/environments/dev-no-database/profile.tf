locals {
  database_mode = "none"
}

output "database_mode" {
  description = "Database profile of this personal dev Terraform root."
  value       = local.database_mode
}
