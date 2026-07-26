# AWS EKS Deployment

## Deployment Flow

```text
                             Developer

                                  |
                                  v

                          Terraform Apply

                                  |
                                  v

                        AWS Infrastructure

                                  |
                                  |
                                  |
                                  v

                                 VPC

                                  |
                                  v

                            EKS Cluster

                                  |
                                  v

                        Managed Node Group


                                  |
                                  v


                        Configure kubeconfig


                                  |
                                  v


                         Bootstrap Argo CD


                                  |
                                  v


                    Deploy AWS Root Application


                                  |
                                  |
                                  |
                                  |
                                  v

                 Argo CD creates Kubernetes Applications

                                  |
             +--------------------+--------------------+
             |                    |                    |
             v                    v                    v


 AWS Load Balancer Controller       Karpenter + CloudNativePG     demo-api

       Application                        Applications           Application


                 |
                 |
                 v


    Kubernetes Resources Ready


                 |
                 v


          ALB Available
```

## Prerequisites

```text
aws
terraform
kubectl
helm
git
curl
```

Confirm identity:

```bash
aws sts get-caller-identity
```

## 1. Prepare Variables

```bash
cp infra/terraform/aws/environments/dev/terraform.tfvars.example \
  infra/terraform/aws/environments/dev/terraform.tfvars
```

Review region, Availability Zones, Kubernetes version, API CIDRs, and tags.

## 2. Validate Terraform

```bash
./scripts/validate-terraform.sh
```

## 3. Plan and Apply

```bash
terraform -chdir=infra/terraform/aws/environments/dev init
terraform -chdir=infra/terraform/aws/environments/dev plan -out=tfplan
terraform -chdir=infra/terraform/aws/environments/dev show tfplan
terraform -chdir=infra/terraform/aws/environments/dev apply tfplan
```

Do not apply an old plan after changing Terraform files.

## 4. Validate EKS

```bash
./scripts/validate-eks-baseline.sh
./scripts/validate-karpenter-foundation.sh
```

## 5. Bootstrap GitOps

```bash
./scripts/bootstrap-eks-argocd.sh
```

The script creates the AWS Load Balancer Controller and Karpenter IRSA
ServiceAccounts, installs Argo CD, reads the current Terraform `vpc_id`, and
applies the rendered AWS Load Balancer Controller Application.

The repository keeps only the `__VPC_ID__` template marker. Do not commit a
real `vpc-*` value.

## 6. Deploy Root Application

```bash
REPO_URL=https://github.com/SterlingAureum/startup-devops-baseline.git \
TARGET_REVISION=feature/v0.6-cloudnativepg-data-platform \
./scripts/deploy-aws-dev-root-app.sh
```

The root Application installs the Karpenter CRDs and controller, application,
FIS, and database capacity definitions, CloudNativePG, the PostgreSQL HA
baseline, and demo-api. v0.6.2 requires no additional Terraform apply. It
dynamically provisions three On-Demand database nodes, their root volumes, and
three 20Gi gp3 PostgreSQL data volumes, so leave the environment running only
when needed.

## 7. Validate Everything

```bash
./scripts/validate-all.sh
```

Manual checks:

```bash
kubectl get nodes
kubectl get applications -n argocd
kubectl get pods -A
kubectl get ingress -n startup-apps
kubectl get ec2nodeclass
kubectl get nodepools,nodeclaims
kubectl get application cloudnative-pg -n argocd
kubectl get pods -n cnpg-system
kubectl get application postgresql-baseline -n argocd
kubectl get cluster,pods,pvc -n data-platform
kubectl get storageclass gp3-cnpg
```

All three EC2NodeClasses and all four NodePools should report `Ready=True`. The
interruption validator should confirm that the controller, SQS queue, and Spot
EventBridge rule use the same queue. The FIS validator should confirm the role,
experiment template, and unique EC2 target tag. Three persistent NodeClaims
should belong to `database-ondemand`; the three temporary application NodePools
should remain idle.

The CloudNativePG validators should report two healthy operator replicas on two
different `workload=system` nodes and a PostgreSQL topology containing one
primary and two streaming replicas. The database instances should occupy three
different `database-ondemand` nodes, span both Availability Zones, and own
three encrypted 20Gi gp3 volumes. `validate-all.sh` does not restart a database
instance.

## 8. Run the PostgreSQL Replica Persistence Test

First run the non-disruptive validator directly when focused database
diagnostics are useful:

```bash
./scripts/validate-cloudnative-pg-persistence.sh
```

Then run the guarded persistence test:

```bash
./scripts/run-cloudnative-pg-persistence-test.sh
```

The script requires typing `restart-replica`. It writes a marker through the
primary, deletes one replica Pod, waits for CloudNativePG to recreate it, and
verifies that the replica reuses the same PVC, PV, and EBS volume. The primary
and second replica remain available. This is not a primary failover test and is
intentionally excluded from `validate-all.sh`.

Expected final output:

```text
CloudNativePG replica recreation and persistent-volume reuse validation passed.
```

## 9. Run the Controlled Scale Test

The following command creates a temporary workload and one small On-Demand
application node. It validates scale-out, deletes the workload, and waits for
consolidation-driven scale-in:

```bash
./scripts/run-karpenter-scale-test.sh
```

This test can incur a small temporary EC2 and EBS charge. Run it intentionally;
it is not part of `validate-all.sh`.

Expected final output:

```text
Karpenter On-Demand scale-out and scale-in validation passed.
```

After the test:

```bash
kubectl get nodeclaims
kubectl get nodes -l karpenter.sh/nodepool
```

The three database NodeClaims and nodes remain. Confirm only that the temporary
application pool returned to zero:

```bash
kubectl get nodeclaims \
  -l karpenter.sh/nodepool=application-ondemand
kubectl get nodes \
  -l karpenter.sh/nodepool=application-ondemand
```

Both scoped commands should return no resources.

## 10. Run the Controlled Spot Test

The Spot test validates interruption-path readiness, creates one temporary Spot
node, confirms the EC2 purchase option, deletes the workload, and waits for
scale-in:

```bash
./scripts/run-karpenter-spot-test.sh
```

Spot availability is not guaranteed. If compatible capacity is unavailable,
the script prints the pod, NodeClaim, and namespace event diagnostics and exits
without falling back to On-Demand.

This test incurs a small temporary EC2 and EBS charge. It does not synthesize
an interruption warning or terminate the node forcibly. A full interruption
and replacement drill should use AWS Fault Injection Service.

Expected final output:

```text
Karpenter Spot scale-out and scale-in validation passed.
```

## 11. Run the Real AWS FIS Interruption Drill

This drill creates an isolated Spot node and starts a real AWS FIS experiment:

```bash
./scripts/run-karpenter-fis-spot-test.sh
```

The script requires typing `interrupt`. Before starting FIS, it proves that the
experiment tag resolves to exactly the EC2 instance hosting the temporary test
Pod. It then validates a replacement Pod on a different Spot instance,
original-instance termination, NodeClaim removal, and final scale-in.

The interruption cannot be undone after EC2 accepts it. This drill incurs
temporary EC2, EBS, and AWS FIS charges and is not part of
`validate-all.sh`.

Expected final output:

```text
Karpenter AWS FIS Spot interruption and replacement validation passed.
```

## 12. Destroy

```bash
./scripts/destroy-aws-dev.sh
```

Delete Kubernetes-managed AWS resources before Terraform destroys the VPC.
