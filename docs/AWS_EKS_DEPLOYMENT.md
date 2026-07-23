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

The root Application installs the Karpenter CRDs first and the controller
afterward. v0.5.1 does not create an `EC2NodeClass` or `NodePool`.

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
kubectl get nodepools,nodeclaims
```

An empty NodePool and NodeClaim listing is expected in v0.5.1.

## 8. Destroy

```bash
./scripts/destroy-aws-dev.sh
```

Delete Kubernetes-managed AWS resources before Terraform destroys the VPC.
