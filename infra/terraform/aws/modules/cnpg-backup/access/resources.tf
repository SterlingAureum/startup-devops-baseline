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
  name               = "${local.name_prefix}-cnpg-backup-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json

  tags = local.common_tags
}

data "aws_iam_policy_document" "backup" {
  statement {
    sid = "BucketMetadata"

    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]

    resources = [local.storage_arn]
  }

  statement {
    sid = "BackupObjects"

    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]

    resources = ["${local.storage_arn}/postgresql-baseline/*"]
  }
}

resource "aws_iam_policy" "this" {
  name        = "${local.name_prefix}-cnpg-backup"
  description = "Least-privilege S3 access for CloudNativePG physical backups and WAL archives."
  policy      = data.aws_iam_policy_document.backup.json

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "this" {
  role       = aws_iam_role.this.name
  policy_arn = aws_iam_policy.this.arn
}
