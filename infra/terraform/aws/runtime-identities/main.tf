data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  runtime_environments = {
    aws-dev  = "dev"
    aws-test = "test"
  }

  cluster_arns = {
    for runtime_environment, environment_name in local.runtime_environments :
    runtime_environment => "arn:${data.aws_partition.current.partition}:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${var.project_name}-${environment_name}"
  }
}

module "runtime_role" {
  for_each = local.runtime_environments
  source   = "../modules/github-actions-runtime-role"

  project_name             = var.project_name
  environment              = each.key
  cluster_arn              = local.cluster_arns[each.key]
  github_repository        = var.github_repository
  github_oidc_provider_arn = var.github_actions_oidc_provider_arn
  tags                     = var.additional_tags
}
