output "secret_name" {
  description = "Name of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = aws_secretsmanager_secret.this.name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = aws_secretsmanager_secret.this.arn
}

output "role_arn" {
  description = "IRSA role ARN used by the External Secrets Operator ServiceAccount."
  value       = aws_iam_role.this.arn
}

output "role_name" {
  description = "Name of the External Secrets Operator IRSA role."
  value       = aws_iam_role.this.name
}

output "policy_arn" {
  description = "ARN of the least-privilege Secrets Manager read policy."
  value       = aws_iam_policy.this.arn
}
