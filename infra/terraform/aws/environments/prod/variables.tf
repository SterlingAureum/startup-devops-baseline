variable "aws_region" {
  description = "AWS region used by the production environment."
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
  default     = "prod"

  validation {
    condition     = var.environment == "prod"
    error_message = "The prod root must use environment = prod so its state cannot claim another environment's resource names."
  }
}

variable "additional_tags" {
  description = "Additional tags applied to supported AWS resources."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block assigned to the production VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zones" {
  description = "Availability Zones used by the production environment."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs ordered to match availability_zones."
  type        = list(string)
  default     = ["10.40.0.0/24", "10.40.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.availability_zones)
    error_message = "public_subnet_cidrs must contain one CIDR for each Availability Zone."
  }
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs ordered to match availability_zones."
  type        = list(string)
  default     = ["10.40.10.0/24", "10.40.11.0/24"]

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
  description = "Use one shared NAT Gateway. Production requires one NAT Gateway per Availability Zone."
  type        = bool
  default     = false

  validation {
    condition     = !var.single_nat_gateway
    error_message = "The production root rejects single_nat_gateway = true."
  }
}

variable "eks_cluster_version" {
  description = "Pinned Kubernetes version for the EKS production environment."
  type        = string
  default     = "1.36"
}

variable "eks_service_ipv4_cidr" {
  description = "Stable EKS Service CIDR referenced by rebuild-safe NetworkPolicy rules."
  type        = string
  default     = "172.22.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.eks_service_ipv4_cidr))
    error_message = "eks_service_ipv4_cidr must be a valid IPv4 CIDR block."
  }
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
  description = "CIDRs allowed to reach the public EKS API endpoint. Supply at runtime; never commit a workstation public IP."
  type        = list(string)
  default     = []

  validation {
    condition = (
      alltrue([for cidr in var.eks_public_access_cidrs : can(cidrnetmask(cidr))]) &&
      !contains(var.eks_public_access_cidrs, "0.0.0.0/0")
    )
    error_message = "eks_public_access_cidrs must contain only valid restricted CIDRs and must not contain 0.0.0.0/0. Use scripts/apply-eks-api-access-cidr.sh for a dynamic workstation IP."
  }
}

variable "eks_enabled_cluster_log_types" {
  description = "Security-relevant EKS control-plane log types sent to CloudWatch."
  type        = list(string)
  default     = ["api", "audit", "authenticator"]

  validation {
    condition = (
      length(var.eks_enabled_cluster_log_types) == length(distinct(var.eks_enabled_cluster_log_types)) &&
      alltrue([
        for log_type in var.eks_enabled_cluster_log_types :
        contains(["api", "audit", "authenticator", "controllerManager", "scheduler"], log_type)
      ])
    )
    error_message = "eks_enabled_cluster_log_types contains an unsupported or duplicate EKS log type."
  }
}

variable "eks_cluster_log_retention_days" {
  description = "CloudWatch retention period for EKS control-plane logs."
  type        = number
  default     = 90

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.eks_cluster_log_retention_days)
    error_message = "eks_cluster_log_retention_days must use a CloudWatch-supported baseline retention value."
  }

  validation {
    condition     = var.eks_cluster_log_retention_days >= 90
    error_message = "The production root requires at least 90 days of EKS control-plane log retention."
  }
}

variable "route53_hosted_zone_name" {
  description = "Existing public Route 53 hosted zone for the demo endpoint."
  type        = string
  default     = "aureumstack.com"
}

variable "demo_api_hostname" {
  description = "Public HTTPS hostname for demo-api."
  type        = string
  default     = "demo.prod.aureumstack.com"
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

variable "cnpg_backup_force_destroy" {
  description = "Allow Terraform destroy to remove all objects and versions from the aws-prod CloudNativePG backup bucket."
  type        = bool
  default     = false

  validation {
    condition     = !var.cnpg_backup_force_destroy
    error_message = "The production backup bucket rejects force_destroy = true."
  }
}

variable "external_secrets_recovery_window_in_days" {
  description = "Secrets Manager recovery window for the persistent aws-prod environment."
  type        = number
  default     = 30

  validation {
    condition = (
      var.external_secrets_recovery_window_in_days == 0 ||
      (
        var.external_secrets_recovery_window_in_days >= 7 &&
        var.external_secrets_recovery_window_in_days <= 30
      )
    )
    error_message = "external_secrets_recovery_window_in_days must be 0 or between 7 and 30."
  }

  validation {
    condition     = var.external_secrets_recovery_window_in_days == 30
    error_message = "The production root requires a 30-day Secrets Manager recovery window."
  }
}
