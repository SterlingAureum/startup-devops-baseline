locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(
    {
      Component = "external-secrets"
    },
    var.tags,
  )
}

locals {
  storage_arn = var.storage_arn
}
