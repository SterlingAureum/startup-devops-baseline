locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Component   = "karpenter-fis"
    },
    var.tags
  )
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

resource "aws_iam_role" "experiment" {
  name = "${local.name_prefix}-fis-spot-interruption-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "fis.amazonaws.com"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:fis:${var.aws_region}:${data.aws_caller_identity.current.account_id}:experiment/*"
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "experiment" {
  name = "${local.name_prefix}-fis-spot-interruption"
  role = aws_iam_role.experiment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DescribeInstances"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      },
      {
        Sid      = "SendSpotInterruption"
        Effect   = "Allow"
        Action   = "ec2:SendSpotInstanceInterruptions"
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*"
      }
    ]
  })
}

resource "aws_fis_experiment_template" "spot_interruption" {
  description = "Interrupt one isolated Karpenter Spot test node."
  role_arn    = aws_iam_role.experiment.arn

  stop_condition {
    source = "none"
  }

  target {
    name           = "oneKarpenterSpotInstance"
    resource_type  = "aws:ec2:spot-instance"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = var.target_tag_key
      value = var.target_tag_value
    }

    filter {
      path   = "State.Name"
      values = ["running"]
    }
  }

  action {
    name        = "interruptKarpenterSpotInstance"
    action_id   = "aws:ec2:send-spot-instance-interruptions"
    description = "Send a two-minute interruption notice to one isolated Karpenter Spot node."

    parameter {
      key   = "durationBeforeInterruption"
      value = "PT2M"
    }

    target {
      key   = "SpotInstances"
      value = "oneKarpenterSpotInstance"
    }
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-karpenter-spot-interruption"
    }
  )
}
