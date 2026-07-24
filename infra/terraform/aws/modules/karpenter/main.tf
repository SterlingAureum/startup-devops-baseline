data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      Component   = "karpenter"
    },
    var.tags,
  )

  interruption_events = {
    "scheduled-change" = {
      source        = ["aws.health"]
      "detail-type" = ["AWS Health Event"]
    }
    "spot-interruption" = {
      source        = ["aws.ec2"]
      "detail-type" = ["EC2 Spot Instance Interruption Warning"]
    }
    "rebalance" = {
      source        = ["aws.ec2"]
      "detail-type" = ["EC2 Instance Rebalance Recommendation"]
    }
    "instance-state" = {
      source        = ["aws.ec2"]
      "detail-type" = ["EC2 Instance State-change Notification"]
    }
    "capacity-reservation" = {
      source        = ["aws.ec2"]
      "detail-type" = ["EC2 Capacity Reservation Instance Interruption Warning"]
    }
  }
}

resource "aws_iam_role" "node" {
  name = "${local.name_prefix}-karpenter-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

resource "aws_eks_access_entry" "node" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.node.arn
  type          = "EC2_LINUX"

  depends_on = [aws_iam_role_policy_attachment.node]

  tags = local.common_tags
}

resource "aws_iam_role" "controller" {
  name = "${local.name_prefix}-karpenter-controller-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = var.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${replace(var.oidc_provider_url, "https://", "")}:aud" = "sts.amazonaws.com"
            "${replace(var.oidc_provider_url, "https://", "")}:sub" = "system:serviceaccount:${var.service_account_namespace}:${var.service_account_name}"
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "controller" {
  for_each = {
    node_lifecycle     = aws_iam_policy.node_lifecycle.arn
    iam_integration    = aws_iam_policy.iam_integration.arn
    eks_integration    = aws_iam_policy.eks_integration.arn
    interruption       = aws_iam_policy.interruption.arn
    zonal_shift        = aws_iam_policy.zonal_shift.arn
    resource_discovery = aws_iam_policy.resource_discovery.arn
  }

  role       = aws_iam_role.controller.name
  policy_arn = each.value
}

resource "aws_sqs_queue" "interruption" {
  name                      = "${var.cluster_name}-karpenter-interruptions"
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true

  tags = local.common_tags
}

resource "aws_sqs_queue_policy" "interruption" {
  queue_url = aws_sqs_queue.interruption.id

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "KarpenterInterruptionPolicy"
    Statement = [
      {
        Sid    = "AllowEventBridgeMessages"
        Effect = "Allow"
        Principal = {
          Service = [
            "events.amazonaws.com",
            "sqs.amazonaws.com",
          ]
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.interruption.arn
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "sqs:*"
        Resource  = aws_sqs_queue.interruption.arn
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "interruption" {
  for_each = local.interruption_events

  name          = "${var.cluster_name}-karpenter-${each.key}"
  description   = "Routes ${each.key} events to the Karpenter interruption queue."
  event_pattern = jsonencode(each.value)

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "interruption" {
  for_each = aws_cloudwatch_event_rule.interruption

  rule      = each.value.name
  target_id = "KarpenterInterruptionQueue"
  arn       = aws_sqs_queue.interruption.arn

  depends_on = [aws_sqs_queue_policy.interruption]
}

resource "aws_ec2_tag" "cluster_security_group_discovery" {
  resource_id = var.cluster_security_group_id
  key         = "karpenter.sh/discovery"
  value       = var.cluster_name
}
