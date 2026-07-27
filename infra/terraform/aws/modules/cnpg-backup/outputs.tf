output "bucket_name" {
  description = "Name of the S3 bucket used for CloudNativePG backups."
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  description = "ARN of the S3 bucket used for CloudNativePG backups."
  value       = aws_s3_bucket.this.arn
}

output "role_arn" {
  description = "IRSA role ARN used by the CloudNativePG cluster ServiceAccount."
  value       = aws_iam_role.this.arn
}

output "role_name" {
  description = "Name of the CloudNativePG backup IAM role."
  value       = aws_iam_role.this.name
}
