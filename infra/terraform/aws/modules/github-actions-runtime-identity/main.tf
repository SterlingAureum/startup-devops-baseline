locals {
  environment_name   = trimprefix(var.environment, "aws-")
  github_environment = "${var.environment}-runtime"
  kubernetes_group   = "demo-api-runtime-qualification"
  oidc_subject       = "repo:${var.github_repository}:environment:${local.github_environment}"
  common_tags = merge(
    {
      Component   = "github-actions-runtime-access"
      Environment = local.environment_name
      Lifecycle   = "environment-disposable"
    },
    var.tags,
  )
}

resource "aws_eks_access_entry" "runtime" {
  cluster_name      = var.cluster_name
  principal_arn     = var.runtime_role_arn
  kubernetes_groups = [local.kubernetes_group]
  type              = "STANDARD"

  tags = local.common_tags
}
