module "cnpg_backup_storage" {
  source = "../../modules/cnpg-backup/storage"
  count  = (local.database_enabled || var.retained_database_bucket) ? 1 : 0

  project_name    = var.project_name
  environment     = var.environment
  aws_region      = var.aws_region
  force_destroy   = var.cnpg_backup_force_destroy
  tags            = merge(var.additional_tags, { BaselineFeature = "cnpg" })
  creation_marker = coalesce(var.database_creation_marker, plantimestamp())
}

module "cnpg_backup_access" {
  source = "../../modules/cnpg-backup/access"
  count  = local.database_enabled ? 1 : 0

  project_name              = var.project_name
  environment               = var.environment
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  service_account_name      = "postgresql-baseline"
  service_account_namespace = "data-platform"
  tags                      = merge(var.additional_tags, { BaselineFeature = "cnpg" })
  storage_arn               = module.cnpg_backup_storage[0].bucket_arn
}

output "cnpg_backup_bucket_name" {
  description = "S3 bucket used for CloudNativePG physical backups and WAL archives."
  value       = one(module.cnpg_backup_storage[*].bucket_name)
}

output "cnpg_backup_bucket_arn" {
  description = "ARN of the CloudNativePG backup bucket."
  value       = one(module.cnpg_backup_storage[*].bucket_arn)
}

output "cnpg_backup_role_arn" {
  description = "IRSA role ARN used by the CloudNativePG cluster ServiceAccount."
  value       = one(module.cnpg_backup_access[*].role_arn)
}

module "external_secrets_storage" {
  source = "../../modules/external-secrets/storage"
  count  = (local.database_enabled || var.retained_database_secret) ? 1 : 0

  project_name            = var.project_name
  environment             = var.environment
  recovery_window_in_days = var.external_secrets_recovery_window_in_days
  tags                    = merge(var.additional_tags, { BaselineFeature = "cnpg" })
  creation_marker         = coalesce(var.database_creation_marker, plantimestamp())
}

module "external_secrets_access" {
  source = "../../modules/external-secrets/access"
  count  = local.database_enabled ? 1 : 0

  project_name              = var.project_name
  environment               = var.environment
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  service_account_name      = "external-secrets"
  service_account_namespace = "external-secrets"
  tags                      = merge(var.additional_tags, { BaselineFeature = "cnpg" })
  storage_arn               = module.external_secrets_storage[0].secret_arn
}

output "external_secrets_secret_name" {
  description = "Name of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = one(module.external_secrets_storage[*].secret_name)
}

output "external_secrets_secret_arn" {
  description = "ARN of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = one(module.external_secrets_storage[*].secret_arn)
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN used by the External Secrets Operator ServiceAccount."
  value       = one(module.external_secrets_access[*].role_arn)
}

output "external_secrets_role_name" {
  description = "Name of the External Secrets Operator IRSA role."
  value       = one(module.external_secrets_access[*].role_name)
}

output "external_secrets_policy_arn" {
  description = "ARN of the least-privilege External Secrets read policy."
  value       = one(module.external_secrets_access[*].policy_arn)
}
