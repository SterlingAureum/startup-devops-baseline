output "role_arn" {
  description = "IRSA role ARN used by the CloudNativePG cluster ServiceAccount."
  value       = aws_iam_role.this.arn
}

output "role_name" {
  description = "Name of the CloudNativePG backup IAM role."
  value       = aws_iam_role.this.name
}
