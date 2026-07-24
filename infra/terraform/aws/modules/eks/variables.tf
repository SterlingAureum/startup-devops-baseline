variable "project_name" {
  description = "Project name used for EKS resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name used for EKS resource naming."
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster."
  type        = string
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane. Set null to let EKS select its current default."
  type        = string
  default     = null
  nullable    = true
}

variable "vpc_id" {
  description = "ID of the VPC hosting the EKS cluster."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs used by the EKS control plane and managed node group."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "At least two private subnets are required for EKS."
  }
}

variable "endpoint_public_access" {
  description = "Whether the EKS API endpoint is reachable from the public internet."
  type        = bool
  default     = true
}

variable "endpoint_private_access" {
  description = "Whether the EKS API endpoint is reachable from within the VPC."
  type        = bool
  default     = true
}

variable "public_access_cidrs" {
  description = "CIDR blocks permitted to reach the public EKS API endpoint. Restrict this for persistent environments."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "enabled_cluster_log_types" {
  description = "EKS control-plane log types sent to CloudWatch. Empty by default to control lab cost."
  type        = list(string)
  default     = []
}

variable "node_group_name" {
  description = "Name suffix for the baseline managed node group."
  type        = string
  default     = "general"
}

variable "node_instance_types" {
  description = "EC2 instance types used by the managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_capacity_type" {
  description = "Capacity type for the managed node group."
  type        = string
  default     = "ON_DEMAND"

  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.node_capacity_type)
    error_message = "node_capacity_type must be ON_DEMAND or SPOT."
  }
}

variable "node_ami_type" {
  description = "AMI type used by the managed node group."
  type        = string
  default     = "AL2023_x86_64_STANDARD"
}

variable "node_disk_size" {
  description = "Root EBS volume size in GiB for managed nodes."
  type        = number
  default     = 30
}

variable "node_desired_size" {
  description = "Desired number of managed nodes."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum number of managed nodes."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum number of managed nodes."
  type        = number
  default     = 3
}

variable "cluster_admin_principal_arn" {
  description = "Optional IAM user or role ARN granted cluster-admin access through an EKS access entry. Do not use an STS assumed-role session ARN."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Additional tags applied directly by the EKS module."
  type        = map(string)
  default     = {}
}
