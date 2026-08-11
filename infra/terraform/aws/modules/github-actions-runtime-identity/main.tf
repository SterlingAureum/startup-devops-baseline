data "aws_partition" "current" {}

locals {
  environment_name  = trimprefix(var.environment, "aws-")
  github_environment = "${var.environment}-runtime"
  kubernetes_group   = "demo-api-runtime-qualification"
  oidc_subject       = "repo:${var.github_repository}:environment:${local.github_environment}"
  name_prefix        = "${var.project_name}-${local.environment_name}"
  common_tags = merge(
    {
      Component   = "github-actions-runtime-identity"
      Environment = local.environment_name
    },
    var.tags,
  )
}

resource "aws_iam_role" "runtime" {
  name = "${local.name_prefix}-github-runtime-read-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = var.github_oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = local.oidc_subject
          }
        }
      }
    ]
  })

  max_session_duration = 3600
  tags                 = local.common_tags
}

resource "aws_iam_role_policy" "runtime" {
  name = "${local.name_prefix}-runtime-read"
  role = aws_iam_role.runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IdentifySession"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
      {
        Sid      = "DescribeExactCluster"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = var.cluster_arn
      }
    ]
  })
}

resource "aws_eks_access_entry" "runtime" {
  cluster_name      = var.cluster_name
  principal_arn     = aws_iam_role.runtime.arn
  kubernetes_groups = [local.kubernetes_group]
  type              = "STANDARD"

  tags = local.common_tags
}
