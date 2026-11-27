resource "aws_secretsmanager_secret" "this" {
  name                    = local.secret_name
  description             = "Database connection material consumed by demo-api through External Secrets Operator."
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(local.common_tags, {
    Name = local.secret_name
  }, contains(["dev", "test"], var.environment) ? { BaselineDevCreationPlan = local.creation_marker } : {})

  lifecycle {
    # Existing or retained resources keep their original ownership marker.
    ignore_changes = [tags["BaselineDevCreationPlan"]]
  }
}
