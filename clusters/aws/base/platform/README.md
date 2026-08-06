# AWS Base Platform Applications

The dev, test, and prod root Applications render this shared Kustomize base.
The checked-in base preserves the validated aws-dev resource identities;
test/prod overlays replace only environment-specific names, paths, IAM and
discovery identity, release values, Secret keys, and address ranges.

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

`cloudnative-pg.yaml` installs the CloudNativePG operator and its CRDs through
the official Helm chart. Two operator replicas run only on the stable
`workload=system` Managed Node Group and are spread across different nodes.

`cert-manager.yaml` installs cert-manager `v1.21.0`, which issues the internal
client and server certificates required by the Barman plugin.

`barman-cloud-plugin.yaml` installs the Barman Cloud CNPG-I plugin `0.13.0`
from official chart `0.7.0` in the same namespace as the CloudNativePG
operator.

`external-secrets.yaml` installs External Secrets Operator `2.8.0` from its
official Helm repository. The controller uses a Terraform-created IRSA role,
is restricted to reconciling `startup-apps`, and does not receive cluster-store,
push-secret, or arbitrary ServiceAccount token-creation capabilities.

`external-secrets-startup-apps.yaml` manages the namespaced AWS Secrets Manager
`SecretStore` and the active demo-api `ExternalSecret` under
`clusters/aws/overlays/dev/security/external-secrets/startup-apps/`. The
ExternalSecret
maps only the `DATABASE_URL` JSON property from the Terraform-managed AWS
Secret into `startup-apps/demo-api-postgresql`. `CreateOrMerge` enables the
initial no-gap handoff without adding an owner reference. `Retain` preserves
the Kubernetes Secret if the provider value is temporarily unavailable.

`postgresql-baseline.yaml` creates a separate Argo CD Application for the
stateful resources under
`clusters/aws/overlays/dev/data-platform/postgresql/`. v0.6.3
runs one PostgreSQL 17.10 primary and two replicas on three dedicated On-Demand
database nodes. Each instance owns one encrypted 20Gi gp3 data volume.
Automated prune is disabled and the stateful resources carry `Prune=false`;
database deletion is handled only by the explicit cleanup and destroy
workflows.

The same Application manages the Barman `ObjectStore` and daily
`ScheduledBackup`. The ObjectStore keeps a repository marker for its S3 bucket
name; `deploy-aws-dev-root-app.sh` renders the Terraform bucket into the live
resource, while `RespectIgnoreDifferences=true` preserves only that
environment-specific field. All other backup settings remain GitOps-managed.

`karpenter-ec2nodeclass.yaml` defines the reusable AWS launch and discovery
configuration for future application NodePools. It can resolve its IAM instance
profile, private subnets, cluster security group, and AL2023 AMIs without
launching an instance.

`karpenter-ec2nodeclass-database.yaml` and
`karpenter-nodepool-database.yaml` define persistent database capacity. The
NodePool uses only On-Demand instances, a database-only taint, a three-node
ceiling, and `WhenEmpty` consolidation. Environment overlays align its
Availability Zones and discovery identity with the selected Terraform root.

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
before the test returns. Their scripts scope cleanup to the selected application
NodePool and never delete the persistent database NodeClaims.
