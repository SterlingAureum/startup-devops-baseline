output "cluster_name" {
  description = "Name of the EKS cluster."
  value       = aws_eks_cluster.this.name
}

output "cluster_arn" {
  description = "ARN of the EKS cluster."
  value       = aws_eks_cluster.this.arn
}

output "cluster_endpoint" {
  description = "API server endpoint of the EKS cluster."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_version" {
  description = "Kubernetes version running on the EKS control plane."
  value       = aws_eks_cluster.this.version
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded certificate authority data for the EKS cluster."
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "cluster_security_group_id" {
  description = "Cluster security group created by EKS."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider used by IRSA."
  value       = aws_iam_openid_connect_provider.cluster.arn
}

output "oidc_provider_url" {
  description = "Issuer URL used by IAM roles for service accounts."
  value       = aws_iam_openid_connect_provider.cluster.url
}

output "node_group_name" {
  description = "Name of the baseline managed node group."
  value       = aws_eks_node_group.general.node_group_name
}

output "node_role_arn" {
  description = "ARN of the managed node IAM role."
  value       = aws_iam_role.node.arn
}

output "ebs_csi_role_arn" {
  description = "IAM role ARN used by the EBS CSI controller service account."
  value       = aws_iam_role.ebs_csi.arn
}

output "addon_names" {
  description = "Names of EKS managed add-ons installed by this module."
  value       = concat(sort([for addon in values(aws_eks_addon.network) : addon.addon_name]), [aws_eks_addon.coredns.addon_name, aws_eks_addon.ebs_csi.addon_name])
}

output "aws_load_balancer_controller_role_arn" {
  description = "IAM role ARN used by the AWS Load Balancer Controller service account."
  value       = aws_iam_role.aws_load_balancer_controller.arn
}
