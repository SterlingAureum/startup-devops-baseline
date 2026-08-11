output "environment_name" {
  description = "Configured environment name."
  value       = var.environment
}

output "cluster_name" {
  description = "Configured EKS cluster name."
  value       = local.cluster_name
}

output "vpc_id" {
  description = "ID of the development VPC."
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the development VPC."
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of public subnets used by internet-facing load balancers."
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of private subnets reserved for EKS worker nodes."
  value       = module.vpc.private_subnet_ids
}

output "nat_gateway_ids" {
  description = "IDs of NAT Gateways used by private subnet routes."
  value       = module.vpc.nat_gateway_ids
}

output "eks_cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "Kubernetes API endpoint of the EKS cluster."
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_log_group_name" {
  description = "CloudWatch log group used by EKS control-plane logging."
  value       = module.eks.cluster_log_group_name
}

output "demo_api_hostname" {
  description = "Public HTTPS hostname for demo-api."
  value       = module.tls_dns.demo_hostname
}

output "demo_api_acm_certificate_arn" {
  description = "ARN of the issued ACM certificate used by demo-api."
  value       = module.tls_dns.certificate_arn
}

output "route53_hosted_zone_id" {
  description = "ID of the public Route 53 hosted zone used by demo-api."
  value       = module.tls_dns.hosted_zone_id
}

output "eks_cluster_version" {
  description = "Kubernetes version running on the EKS cluster."
  value       = module.eks.cluster_version
}

output "eks_service_ipv4_cidr" {
  description = "Stable IPv4 Service CIDR assigned to the EKS cluster."
  value       = module.eks.service_ipv4_cidr
}

output "eks_cluster_security_group_id" {
  description = "EKS-managed cluster security group ID."
  value       = module.eks.cluster_security_group_id
}

output "eks_oidc_provider_arn" {
  description = "IAM OIDC provider ARN for EKS workload identities."
  value       = module.eks.oidc_provider_arn
}

output "karpenter_controller_role_arn" {
  description = "IAM role ARN to annotate on the Karpenter controller service account."
  value       = module.karpenter.controller_role_arn
}

output "karpenter_node_role_arn" {
  description = "IAM role ARN used by nodes provisioned through Karpenter."
  value       = module.karpenter.node_role_arn
}

output "karpenter_node_role_name" {
  description = "IAM role name referenced by the future EC2NodeClass."
  value       = module.karpenter.node_role_name
}

output "karpenter_interruption_queue_name" {
  description = "SQS queue name configured in the future Karpenter Helm release."
  value       = module.karpenter.interruption_queue_name
}

output "karpenter_event_rule_names" {
  description = "EventBridge rules that publish interruption events to Karpenter."
  value       = module.karpenter.event_rule_names
}

output "karpenter_fis_role_arn" {
  description = "IAM role assumed by AWS FIS for the Karpenter Spot interruption drill."
  value       = module.fis.experiment_role_arn
}

output "karpenter_fis_experiment_template_id" {
  description = "AWS FIS experiment template ID for the Karpenter Spot interruption drill."
  value       = module.fis.experiment_template_id
}

output "karpenter_fis_target_tag_key" {
  description = "EC2 tag key used to isolate the FIS Spot interruption target."
  value       = module.fis.target_tag_key
}

output "karpenter_fis_target_tag_value" {
  description = "EC2 tag value used to isolate the FIS Spot interruption target."
  value       = module.fis.target_tag_value
}

output "eks_node_group_name" {
  description = "Name of the baseline EKS managed node group."
  value       = module.eks.node_group_name
}

output "eks_addon_names" {
  description = "EKS managed add-ons installed by Terraform."
  value       = module.eks.addon_names
}

output "aws_load_balancer_controller_role_arn" {
  description = "IAM role ARN used by the AWS Load Balancer Controller service account."
  value       = module.eks.aws_load_balancer_controller_role_arn
}

output "cnpg_backup_bucket_name" {
  description = "S3 bucket used for CloudNativePG physical backups and WAL archives."
  value       = module.cnpg_backup.bucket_name
}

output "cnpg_backup_bucket_arn" {
  description = "ARN of the CloudNativePG backup bucket."
  value       = module.cnpg_backup.bucket_arn
}

output "cnpg_backup_role_arn" {
  description = "IRSA role ARN used by the CloudNativePG cluster ServiceAccount."
  value       = module.cnpg_backup.role_arn
}

output "external_secrets_secret_name" {
  description = "Name of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = module.external_secrets.secret_name
}

output "external_secrets_secret_arn" {
  description = "ARN of the Secrets Manager secret reserved for demo-api PostgreSQL material."
  value       = module.external_secrets.secret_arn
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN used by the External Secrets Operator ServiceAccount."
  value       = module.external_secrets.role_arn
}

output "external_secrets_role_name" {
  description = "Name of the External Secrets Operator IRSA role."
  value       = module.external_secrets.role_name
}

output "external_secrets_policy_arn" {
  description = "ARN of the least-privilege External Secrets read policy."
  value       = module.external_secrets.policy_arn
}

output "github_actions_runtime_role_arn" {
  description = "IAM role ARN configured as AWS_RUNTIME_ROLE_ARN in aws-dev-runtime."
  value       = try(module.github_actions_runtime_identity[0].role_arn, null)
}

output "github_actions_runtime_oidc_subject" {
  description = "Exact GitHub OIDC subject accepted by the aws-dev runtime role."
  value       = try(module.github_actions_runtime_identity[0].oidc_subject, null)
}
