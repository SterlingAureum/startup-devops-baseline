moved {
  from = module.cnpg_backup.aws_s3_bucket.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_public_access_block.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_public_access_block.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_ownership_controls.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_ownership_controls.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_versioning.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_versioning.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_server_side_encryption_configuration.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_server_side_encryption_configuration.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_lifecycle_configuration.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_lifecycle_configuration.this
}

moved {
  from = module.cnpg_backup.aws_s3_bucket_policy.this
  to   = module.cnpg_backup_storage[0].aws_s3_bucket_policy.this
}

moved {
  from = module.cnpg_backup.aws_iam_role.this
  to   = module.cnpg_backup_access[0].aws_iam_role.this
}

moved {
  from = module.cnpg_backup.aws_iam_policy.this
  to   = module.cnpg_backup_access[0].aws_iam_policy.this
}

moved {
  from = module.cnpg_backup.aws_iam_role_policy_attachment.this
  to   = module.cnpg_backup_access[0].aws_iam_role_policy_attachment.this
}

moved {
  from = module.external_secrets.aws_secretsmanager_secret.this
  to   = module.external_secrets_storage[0].aws_secretsmanager_secret.this
}

moved {
  from = module.external_secrets.aws_iam_role.this
  to   = module.external_secrets_access[0].aws_iam_role.this
}

moved {
  from = module.external_secrets.aws_iam_policy.this
  to   = module.external_secrets_access[0].aws_iam_policy.this
}

moved {
  from = module.external_secrets.aws_iam_role_policy_attachment.this
  to   = module.external_secrets_access[0].aws_iam_role_policy_attachment.this
}
