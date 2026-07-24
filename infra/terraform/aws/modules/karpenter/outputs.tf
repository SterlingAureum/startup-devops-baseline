output "controller_role_arn" {
  description = "ARN of the Karpenter controller IRSA role."
  value       = aws_iam_role.controller.arn
}

output "controller_role_name" {
  description = "Name of the Karpenter controller IRSA role."
  value       = aws_iam_role.controller.name
}

output "node_role_arn" {
  description = "ARN of the IAM role used by Karpenter-provisioned nodes."
  value       = aws_iam_role.node.arn
}

output "node_role_name" {
  description = "Name of the IAM role used by Karpenter-provisioned nodes."
  value       = aws_iam_role.node.name
}

output "interruption_queue_name" {
  description = "Name of the Karpenter interruption queue."
  value       = aws_sqs_queue.interruption.name
}

output "interruption_queue_arn" {
  description = "ARN of the Karpenter interruption queue."
  value       = aws_sqs_queue.interruption.arn
}

output "event_rule_names" {
  description = "Names of EventBridge rules that feed the Karpenter interruption queue."
  value       = sort([for rule in values(aws_cloudwatch_event_rule.interruption) : rule.name])
}
