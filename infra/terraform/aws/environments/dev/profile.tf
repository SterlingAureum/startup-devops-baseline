locals {
  database_mode = "cnpg"
}

output "database_mode" {
  description = "Database profile of this personal dev Terraform root."
  value       = local.database_mode
}
