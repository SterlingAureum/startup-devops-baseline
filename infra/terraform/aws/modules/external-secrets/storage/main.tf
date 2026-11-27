locals {
  name_prefix = "${var.project_name}-${var.environment}"
  secret_name = "${local.name_prefix}/demo-api/postgresql"

  common_tags = merge(
    {
      Component = "external-secrets"
    },
    var.tags,
  )
}

locals {
  creation_marker = var.creation_marker
}
