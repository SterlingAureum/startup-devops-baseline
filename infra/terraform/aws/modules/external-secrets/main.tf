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

resource "aws_secretsmanager_secret" "this" {
  name                    = local.secret_name
  description             = "Database connection material consumed by demo-api through External Secrets Operator."
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(local.common_tags, {
    Name = local.secret_name
  })
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values = [
        "system:serviceaccount:${var.service_account_namespace}:${var.service_account_name}",
      ]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${local.name_prefix}-external-secrets-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json

  tags = local.common_tags
}

data "aws_iam_policy_document" "read_secret" {
  statement {
    sid    = "ReadDemoApiPostgresqlSecret"
    effect = "Allow"

    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]

    resources = [aws_secretsmanager_secret.this.arn]
  }
}

resource "aws_iam_policy" "this" {
  name        = "${local.name_prefix}-external-secrets-read"
  description = "Read-only access to the demo-api PostgreSQL secret for External Secrets Operator."
  policy      = data.aws_iam_policy_document.read_secret.json

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "this" {
  role       = aws_iam_role.this.name
  policy_arn = aws_iam_policy.this.arn
}
