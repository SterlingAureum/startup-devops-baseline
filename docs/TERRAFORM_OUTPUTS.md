# Terraform Outputs

Run:

```bash
terraform -chdir=infra/terraform/aws/environments/dev output
```

## Network

- `vpc_id`: rendered into the AWS Load Balancer Controller Application by
  `bootstrap-eks-argocd.sh`.
- `public_subnet_ids`: internet-facing load balancer discovery.
- `private_subnet_ids`: EKS worker-node placement.
- `nat_gateway_ids`: cost and teardown verification.

## EKS

- `eks_cluster_name`: kubeconfig and bootstrap scripts.
- `eks_cluster_endpoint`: Kubernetes API endpoint.
- `eks_cluster_version`: EKS Kubernetes minor version.
- `eks_cluster_security_group_id`: EKS-managed security group.
- `eks_node_group_name`: default On-Demand node group.
- `eks_addon_names`: Terraform-managed EKS add-ons.

## Identity

- `eks_oidc_provider_arn`: IRSA trust provider.
- `aws_load_balancer_controller_role_arn`: read by `bootstrap-eks-argocd.sh` to annotate the controller ServiceAccount.

## Karpenter Foundation

- `karpenter_controller_role_arn`: read by `bootstrap-eks-argocd.sh` to
  annotate the Karpenter ServiceAccount.
- `karpenter_node_role_arn`: identity authorized to join EKS as an EC2 Linux node.
- `karpenter_node_role_name`: `EC2NodeClass.spec.role` contract, checked by
  `validate-karpenter-nodeclass.sh`.
- `karpenter_interruption_queue_name`: Karpenter Helm
  `settings.interruptionQueue` value.
- `karpenter_event_rule_names`: interruption rules managed by Terraform.

## AWS FIS Spot Drill

- `karpenter_fis_role_arn`: role assumed by AWS FIS for the interruption
  action.
- `karpenter_fis_experiment_template_id`: template read and started by the FIS
  validation scripts.
- `karpenter_fis_target_tag_key`: EC2 target tag key shared with the dedicated
  FIS EC2NodeClass.
- `karpenter_fis_target_tag_value`: environment-specific EC2 target tag value.

## Operational Rule

Terraform outputs are not committed to Git. Run `bootstrap-eks-argocd.sh`
after infrastructure creation or recreation; it reads the current VPC ID and
IRSA role ARNs, then applies the environment-specific bootstrap resources.
