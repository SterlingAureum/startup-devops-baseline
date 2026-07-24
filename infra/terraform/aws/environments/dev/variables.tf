variable "aws_region" {
  description = "AWS region used by the development environment."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tags."
  type        = string
  default     = "startup-devops-baseline"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"
}

variable "additional_tags" {
  description = "Additional tags applied to supported AWS resources."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block assigned to the development VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "availability_zones" {
  description = "Availability Zones used by the development environment."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs ordered to match availability_zones."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.availability_zones)
    error_message = "public_subnet_cidrs must contain one CIDR for each Availability Zone."
  }
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs ordered to match availability_zones."
  type        = list(string)
  default     = ["10.20.10.0/24", "10.20.11.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == length(var.availability_zones)
    error_message = "private_subnet_cidrs must contain one CIDR for each Availability Zone."
  }
}

variable "enable_nat_gateway" {
  description = "Whether private subnets receive outbound internet access through NAT Gateway."
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Use one shared NAT Gateway in development to reduce cost."
  type        = bool
  default     = true
}

variable "eks_cluster_version" {
  description = "Pinned Kubernetes version for the EKS development environment."
  type        = string
  default     = "1.36"
}

variable "eks_endpoint_public_access" {
  description = "Enable public access to the EKS Kubernetes API endpoint."
  type        = bool
  default     = true
}

variable "eks_endpoint_private_access" {
  description = "Enable private access to the EKS Kubernetes API endpoint."
  type        = bool
  default     = true
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "eks_enabled_cluster_log_types" {
  description = "EKS control-plane log types sent to CloudWatch."
  type        = list(string)
  default     = []
}

variable "eks_node_group_name" {
  description = "Name suffix for the baseline EKS managed node group."
  type        = string
  default     = "general"
}

variable "eks_node_instance_types" {
  description = "EC2 instance types for the EKS managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "eks_node_capacity_type" {
  description = "Capacity type for the EKS managed node group."
  type        = string
  default     = "ON_DEMAND"
}

variable "eks_node_ami_type" {
  description = "AMI type used by EKS managed nodes."
  type        = string
  default     = "AL2023_x86_64_STANDARD"
}

variable "eks_node_disk_size" {
  description = "Root disk size in GiB for EKS managed nodes."
  type        = number
  default     = 30
}

variable "eks_node_desired_size" {
  description = "Desired number of EKS managed nodes."
  type        = number
  default     = 2
}

variable "eks_node_min_size" {
  description = "Minimum number of stable system nodes that host platform controllers."
  type        = number
  default     = 2
}

variable "eks_node_max_size" {
  description = "Maximum number of EKS managed nodes."
  type        = number
  default     = 3
}

variable "eks_cluster_admin_principal_arn" {
  description = "Optional long-lived IAM role or user ARN granted cluster-admin through an EKS access entry."
  type        = string
  default     = null
  nullable    = true
}
