# Exercise the actual dev module counts without creating AWS resources.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }

  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}

mock_provider "tls" {}

override_module {
  target = module.vpc
}

override_module {
  target = module.eks
  outputs = {
    oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/example.invalid"
    oidc_provider_url = "https://example.invalid"
  }
}

override_module {
  target = module.karpenter
}

override_module {
  target = module.fis
}

override_module {
  target = module.tls_dns
}

run "fresh_base" {
  command = plan

  variables {
    database_mode = "none"
  }

  assert {
    condition = (
      length(module.cnpg_backup_storage) == 0 && length(module.external_secrets_storage) == 0 &&
      length(module.cnpg_backup_access) == 0 && length(module.external_secrets_access) == 0
    )
    error_message = "A fresh base dev environment requested database resources."
  }
}

run "retain_storage_only" {
  command = plan

  variables {
    database_mode            = "none"
    retained_database_bucket = true
    retained_database_secret = true
  }

  assert {
    condition = (
      length(module.cnpg_backup_storage) == 1 && length(module.external_secrets_storage) == 1 &&
      length(module.cnpg_backup_access) == 0 && length(module.external_secrets_access) == 0
    )
    error_message = "Retained storage must remain declared independently of database access."
  }
}

run "with_database" {
  command = plan

  variables {
    database_mode = "cnpg"
  }

  assert {
    condition = (
      length(module.cnpg_backup_storage) == 1 && length(module.external_secrets_storage) == 1 &&
      length(module.cnpg_backup_access) == 1 && length(module.external_secrets_access) == 1
    )
    error_message = "CNPG requires both storage and workload access."
  }
}
