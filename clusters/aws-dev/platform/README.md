# aws-dev Platform Applications

The root Application recursively manages the manifests in this directory.

`aws-load-balancer-controller.yaml` is also a bootstrap template because its
Helm values require the environment-specific Terraform output `vpc_id`. The
bootstrap script replaces `__VPC_ID__` in a temporary file and applies the
resulting Argo CD Application before the root Application syncs. The root uses
`RespectIgnoreDifferences=true` to preserve only the live
`/spec/source/helm/valuesObject/vpcId` field for this child Application. All
other values and prune ownership remain managed by Git without writing the real
VPC ID back to the repository.

Karpenter is split into two Applications:

- `karpenter-crd.yaml` owns the Karpenter CRDs.
- `karpenter.yaml` installs the controller with CRD installation disabled.

The controller runs only on the stable Managed Node Group nodes labeled
`workload=system`. `EC2NodeClass` and `NodePool` resources are intentionally
deferred to a later v0.5 increment.
