output "experiment_role_arn" {
  description = "IAM role assumed by AWS FIS for the Spot interruption experiment."
  value       = aws_iam_role.experiment.arn
}

output "experiment_template_id" {
  description = "AWS FIS experiment template ID for the isolated Spot interruption drill."
  value       = aws_fis_experiment_template.spot_interruption.id
}

output "target_tag_key" {
  description = "EC2 tag key used by the FIS target."
  value       = var.target_tag_key
}

output "target_tag_value" {
  description = "EC2 tag value used by the FIS target."
  value       = var.target_tag_value
}
