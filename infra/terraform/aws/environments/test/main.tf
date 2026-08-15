locals {
  cluster_name = "${var.project_name}-${var.environment}"
}

module "vpc" {
  source = "../../modules/vpc"

  project_name         = var.project_name
  environment          = var.environment
  cluster_name         = local.cluster_name
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  enable_nat_gateway   = var.enable_nat_gateway
  single_nat_gateway   = var.single_nat_gateway
}

module "eks" {
  source = "../../modules/eks"

  project_name                = var.project_name
  environment                 = var.environment
  cluster_name                = local.cluster_name
  cluster_version             = var.eks_cluster_version
  service_ipv4_cidr           = var.eks_service_ipv4_cidr
  vpc_id                      = module.vpc.vpc_id
  private_subnet_ids          = module.vpc.private_subnet_ids
  endpoint_public_access      = var.eks_endpoint_public_access
  endpoint_private_access     = var.eks_endpoint_private_access
  public_access_cidrs         = var.eks_public_access_cidrs
  enabled_cluster_log_types   = var.eks_enabled_cluster_log_types
  cluster_log_retention_days  = var.eks_cluster_log_retention_days
  node_group_name             = var.eks_node_group_name
  node_instance_types         = var.eks_node_instance_types
  node_capacity_type          = var.eks_node_capacity_type
  node_ami_type               = var.eks_node_ami_type
  node_disk_size              = var.eks_node_disk_size
  node_desired_size           = var.eks_node_desired_size
  node_min_size               = var.eks_node_min_size
  node_max_size               = var.eks_node_max_size
  cluster_admin_principal_arn = var.eks_cluster_admin_principal_arn
}

module "tls_dns" {
  source = "../../modules/tls-dns"

  hosted_zone_name = var.route53_hosted_zone_name
  demo_hostname    = var.demo_api_hostname
  tags             = var.additional_tags
}

module "karpenter" {
  source = "../../modules/karpenter"

  project_name              = var.project_name
  environment               = var.environment
  aws_region                = var.aws_region
  cluster_name              = module.eks.cluster_name
  cluster_arn               = module.eks.cluster_arn
  cluster_security_group_id = module.eks.cluster_security_group_id
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  tags                      = var.additional_tags
}

module "fis" {
  source = "../../modules/fis"

  project_name     = var.project_name
  environment      = var.environment
  aws_region       = var.aws_region
  target_tag_key   = "KarpenterFISTest"
  target_tag_value = "${local.cluster_name}-spot-interruption"
  tags             = var.additional_tags
}

module "cnpg_backup" {
  source = "../../modules/cnpg-backup"

  project_name              = var.project_name
  environment               = var.environment
  aws_region                = var.aws_region
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  force_destroy             = var.cnpg_backup_force_destroy
  service_account_name      = "postgresql-baseline"
  service_account_namespace = "data-platform"
  tags                      = var.additional_tags
}

module "external_secrets" {
  source = "../../modules/external-secrets"

  project_name              = var.project_name
  environment               = var.environment
  oidc_provider_arn         = module.eks.oidc_provider_arn
  oidc_provider_url         = module.eks.oidc_provider_url
  service_account_name      = "external-secrets"
  service_account_namespace = "external-secrets"
  recovery_window_in_days   = var.external_secrets_recovery_window_in_days
  tags                      = var.additional_tags
}

module "github_actions_runtime_identity" {
  count  = var.enable_github_actions_runtime_identity ? 1 : 0
  source = "../../modules/github-actions-runtime-identity"

  project_name     = var.project_name
  environment      = "aws-test"
  cluster_name     = module.eks.cluster_name
  runtime_role_arn = var.github_actions_runtime_role_arn
  tags             = var.additional_tags
}
