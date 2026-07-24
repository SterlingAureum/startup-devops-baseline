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
`workload=system`.

`karpenter-ec2nodeclass.yaml` defines the reusable AWS launch and discovery
configuration for future application NodePools. It can resolve its IAM instance
profile, private subnets, cluster security group, and AL2023 AMIs without
launching an instance.

`karpenter-nodepool-ondemand.yaml` and `karpenter-nodepool-spot.yaml` define
the normal application capacity tiers. Both use `workload=application`, but
each has a distinct `NoSchedule` taint so a workload opts in to exactly one
tier. Both pools are limited to small development capacity.

`karpenter-ec2nodeclass-fis.yaml` and
`karpenter-nodepool-spot-fis.yaml` provide a third, test-only capacity
contract. Its EC2 instances receive the unique `KarpenterFISTest` tag consumed
by the Terraform-managed AWS FIS template. Normal application nodes never
receive this tag.

The scale and interruption workloads under `examples/karpenter/` are not
GitOps-managed. They are applied only during controlled validation and removed
before the test returns.
