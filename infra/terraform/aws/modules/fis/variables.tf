variable "project_name" {
  description = "Project name used for FIS resource naming and tags."
  type        = string
}

variable "environment" {
  description = "Environment name used for FIS resource naming and tags."
  type        = string
}

variable "aws_region" {
  description = "AWS region containing the FIS experiment and target Spot instance."
  type        = string
}

variable "target_tag_key" {
  description = "EC2 tag key that isolates the Spot instance eligible for interruption."
  type        = string
}

variable "target_tag_value" {
  description = "EC2 tag value that isolates the Spot instance eligible for interruption."
  type        = string
}

variable "tags" {
  description = "Additional tags applied to supported FIS resources."
  type        = map(string)
  default     = {}
}
