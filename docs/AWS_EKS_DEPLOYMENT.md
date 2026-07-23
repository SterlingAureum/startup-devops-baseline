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


 AWS Load Balancer Controller              Karpenter              demo-api

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
TARGET_REVISION=feature/v0.5-karpenter-autoscaling \
./scripts/deploy-aws-dev-root-app.sh
```

The root Application installs the Karpenter CRDs first, the controller
afterward, the `application` EC2NodeClass, and finally the
`application-ondemand` and `application-spot` NodePools.

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
kubectl get ec2nodeclass application
kubectl get nodepools,nodeclaims
```

The EC2NodeClass and both NodePools should report `Ready=True`. The interruption
validator should confirm that the controller, SQS queue, and Spot EventBridge
rule use the same queue. No NodeClaims or Karpenter-provisioned nodes should
exist in the idle baseline.

## 8. Run the Controlled Scale Test

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

Both commands should return no Karpenter capacity.

## 9. Run the Controlled Spot Test

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

## 10. Destroy

```bash
./scripts/destroy-aws-dev.sh
```

Delete Kubernetes-managed AWS resources before Terraform destroys the VPC.
