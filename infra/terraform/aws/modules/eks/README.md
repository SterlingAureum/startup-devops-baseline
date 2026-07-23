# EKS module

This module implements the EKS control-plane and stable managed-node baseline.

## Resources

- EKS control plane using private subnets;
- public and private Kubernetes API endpoint access;
- EKS cluster IAM role;
- one On-Demand managed node group in private subnets;
- managed-node IAM role;
- IAM OIDC provider for workload identities;
- IRSA role for the Amazon EBS CSI driver;
- EKS managed add-ons: VPC CNI, CoreDNS, kube-proxy, and EBS CSI;
- optional EKS access entry and cluster-admin policy association.

## Access model

The cluster uses `API_AND_CONFIG_MAP` authentication while the repository
transitions toward EKS access entries. The Terraform caller retains bootstrap
administrator access. Set `cluster_admin_principal_arn` to an IAM role or IAM
user ARN when explicit long-lived access should also be managed by Terraform.
Do not provide an STS assumed-role session ARN.

## API endpoint

The development environment enables both public and private endpoint access.
The example initially permits `0.0.0.0/0` so the lab can be bootstrapped from a
local workstation. Replace `public_access_cidrs` with the operator's public
CIDR before keeping the environment online.

## Node baseline

The default managed node group uses two `t3.medium` On-Demand system nodes with
a minimum of two and maximum of three. Nodes are labeled `workload=system` so
platform controllers remain separate from future Karpenter application nodes.

## AWS Load Balancer Controller IAM

The module creates a dedicated IRSA role and customer-managed policy for the `kube-system/aws-load-balancer-controller` ServiceAccount. The policy is based on the upstream AWS Load Balancer Controller v2.14.1 installation policy.

The Kubernetes ServiceAccount is intentionally created and annotated by `scripts/bootstrap-eks-argocd.sh`, because its role ARN contains the AWS account ID and must not be hardcoded in Git.
