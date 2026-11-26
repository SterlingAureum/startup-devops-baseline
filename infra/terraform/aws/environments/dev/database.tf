module "cnpg_backup" {
  source = "../../modules/cnpg-backup"

  project_name              = var.project_name
  environment               = var.environment
  aws_region                = var.aws_region
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  force_destroy             = var.cnpg_backup_force_destroy
  service_account_name      = "postgresql-baseline"
  service_account_namespace = "data-platform"
  tags                      = merge(var.additional_tags, { BaselineFeature = "cnpg" })
}

module "external_secrets" {
  source = "../../modules/external-secrets"

  project_name              = var.project_name
  environment               = var.environment
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  service_account_name      = "external-secrets"
  service_account_namespace = "external-secrets"
  recovery_window_in_days   = var.external_secrets_recovery_window_in_days
  tags                      = merge(var.additional_tags, { BaselineFeature = "cnpg" })
}

output "cnpg_backup_bucket_name" {
  description = "S3 bucket used for CloudNativePG physical backups and WAL archives."
  value       = module.cnpg_backup.bucket_name
}

output "cnpg_backup_bucket_arn" {
  description = "ARN of the CloudNativePG backup bucket."
  value       = module.cnpg_backup.bucket_arn
}

output "cnpg_backup_role_arn" {
  description = "IRSA role ARN used by the CloudNativePG cluster ServiceAccount."
  value       = module.cnpg_backup.role_arn
}

output "external_secrets_secret_name" {
  description = "Name of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = module.external_secrets.secret_name
}

output "external_secrets_secret_arn" {
  description = "ARN of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = module.external_secrets.secret_arn
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN used by the External Secrets Operator ServiceAccount."
  value       = module.external_secrets.role_arn
}

output "external_secrets_role_name" {
  description = "Name of the External Secrets Operator IRSA role."
  value       = module.external_secrets.role_name
}

output "external_secrets_policy_arn" {
  description = "ARN of the least-privilege External Secrets read policy."
  value       = module.external_secrets.policy_arn
}
