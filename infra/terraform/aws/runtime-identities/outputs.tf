output "github_actions_runtime_role_arns" {
  description = "Persistent runtime role ARN keyed by GitHub runtime environment."
  value       = { for environment, role in module.runtime_role : environment => role.role_arn }
}

output "aws_dev_runtime_role_arn" {
  description = "Role ARN configured as AWS_RUNTIME_ROLE_ARN in aws-dev-runtime."
  value       = module.runtime_role["aws-dev"].role_arn
}

output "aws_test_runtime_role_arn" {
  description = "Role ARN configured as AWS_RUNTIME_ROLE_ARN in aws-test-runtime."
  value       = module.runtime_role["aws-test"].role_arn
}

output "github_actions_runtime_oidc_subjects" {
  description = "Exact GitHub Environment OIDC subjects accepted by the roles."
  value       = { for environment, role in module.runtime_role : environment => role.oidc_subject }
}
