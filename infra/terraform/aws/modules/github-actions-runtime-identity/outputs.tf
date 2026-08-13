output "role_arn" {
  description = "Environment-isolated IAM role configured as AWS_RUNTIME_ROLE_ARN."
  value       = aws_iam_role.runtime.arn
}

output "role_name" {
  description = "Name of the trusted runtime read role."
  value       = aws_iam_role.runtime.name
}

output "github_environment" {
  description = "GitHub Environment whose OIDC subject may assume the role."
  value       = local.github_environment
}

output "oidc_subject" {
  description = "Exact GitHub OIDC subject accepted by the role."
  value       = local.oidc_subject
}

output "kubernetes_group" {
  description = "Kubernetes group mapped by the EKS access entry."
  value       = local.kubernetes_group
}
