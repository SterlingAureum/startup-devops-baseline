data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  state_keys = merge({
    bootstrap          = "bootstrap/terraform.tfstate"
    runtime-identities = "runtime-identities/terraform.tfstate"
    dev                = "environments/dev/terraform.tfstate"
    test               = "environments/test/terraform.tfstate"
    prod               = "environments/prod/terraform.tfstate"
  }, var.state_key_overrides)
  use_kms    = var.state_encryption != "sse-s3"
  create_kms = var.state_encryption == "managed-kms"
  key_arn    = local.create_kms ? aws_kms_key.state[0].arn : var.existing_kms_key_arn
}

data "aws_iam_policy_document" "kms" {
  statement {
    sid    = "EnableAccountIAMPermissions"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }
}

resource "aws_kms_key" "state" {
  count = local.create_kms ? 1 : 0

  description             = "Customer-managed key for ${var.project_name} Terraform state and lock files"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "state" {
  count = local.create_kms ? 1 : 0

  name          = var.state_kms_alias
  target_key_id = aws_kms_key.state[0].key_id
}

moved {
  from = aws_kms_key.state
  to   = aws_kms_key.state[0]
}

moved {
  from = aws_kms_alias.state
  to   = aws_kms_alias.state[0]
}

resource "aws_s3_bucket" "state" {
  bucket        = var.state_bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = length(distinct(flatten([
        for key in values(local.state_keys) : [key, "${key}.tflock"]
      ]))) == 2 * length(local.state_keys)
      error_message = "State and lock object paths must be distinct across roots."
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    bucket_key_enabled = local.use_kms ? true : null

    apply_server_side_encryption_by_default {
      kms_master_key_id = local.key_arn
      sse_algorithm     = local.use_kms ? "aws:kms" : "AES256"
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.bucket.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}

data "aws_iam_policy_document" "root_state_access" {
  for_each = local.state_keys

  statement {
    sid       = "ListExactStateAndLockKeys"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = [each.value, "${each.value}.tflock"]
    }
  }

  statement {
    sid    = "ReadWriteExactStateObject"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = ["${aws_s3_bucket.state.arn}/${each.value}"]
  }

  statement {
    sid    = "ManageExactLockObject"
    effect = "Allow"

    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = ["${aws_s3_bucket.state.arn}/${each.value}.tflock"]
  }

  dynamic "statement" {
    for_each = local.use_kms ? [1] : []
    content {
      sid    = "UseStateEncryptionKeyThroughS3"
      effect = "Allow"

      actions = [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:Encrypt",
        "kms:GenerateDataKey",
      ]

      resources = [local.key_arn]

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["s3.${var.aws_region}.${data.aws_partition.current.dns_suffix}"]
      }
    }
  }
}

resource "aws_iam_policy" "root_state_access" {
  for_each = local.state_keys

  name        = "${var.project_name}-terraform-state-${each.key}"
  description = "Exact state and lock-key access for the ${each.key} Terraform root"
  policy      = data.aws_iam_policy_document.root_state_access[each.key].json
}
