output "secret_name" {
  description = "Name of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = aws_secretsmanager_secret.this.name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = aws_secretsmanager_secret.this.arn
}
