provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        ManagedBy   = "terraform"
        Project     = var.project_name
        Environment = "state-bootstrap"
      },
      var.additional_tags,
    )
  }
}
