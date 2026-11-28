output "state_bucket_name" {
  description = "S3 bucket containing the isolated Terraform state objects."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state bucket."
  value       = aws_s3_bucket.state.arn
}

output "state_kms_key_arn" {
  description = "ARN of the customer-managed KMS key used for state encryption."
  value       = local.key_arn
}

output "state_kms_alias" {
  description = "KMS alias used by the state foundation."
  value       = one(aws_kms_alias.state[*].name)
}

output "state_keys" {
  description = "Exact backend key assigned to each Terraform root."
  value       = local.state_keys
}

output "root_state_access_policy_arns" {
  description = "Unattached least-privilege IAM policy ARN for each Terraform root."
  value       = { for root, policy in aws_iam_policy.root_state_access : root => policy.arn }
}

output "backend_configuration" {
  description = "Non-credential backend values. Materialize them only in ignored private tfbackend files."
  value = {
    for root, key in local.state_keys : root => merge({
      bucket       = aws_s3_bucket.state.id
      encrypt      = true
      key          = key
      region       = var.aws_region
      use_lockfile = true
    }, local.use_kms ? { kms_key_id = local.key_arn } : {})
  }
}
