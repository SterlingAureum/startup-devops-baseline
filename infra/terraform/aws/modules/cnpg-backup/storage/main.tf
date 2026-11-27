locals {
  name_prefix = "${var.project_name}-${var.environment}"
  bucket_name = lower(
    "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-cnpg"
  )

  common_tags = merge(
    {
      Component = "cnpg-backup"
    },
    var.tags,
  )
}

locals {
  creation_marker = var.creation_marker
}
