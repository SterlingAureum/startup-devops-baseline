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
                 +----------------+----------------+
                 |                                 |
                 v                                 v


    AWS Load Balancer Controller                demo-api

          Application                          Application


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
```

## 5. Synchronize VPC ID

```bash
terraform -chdir=infra/terraform/aws/environments/dev output -raw vpc_id
```

Ensure the same value exists in `clusters/aws-dev/platform/aws-load-balancer-controller.yaml` before deploying the root Application.

## 6. Bootstrap GitOps

```bash
./scripts/bootstrap-eks-argocd.sh
```

## 7. Deploy Root Application

```bash
REPO_URL=https://github.com/SterlingAureum/startup-devops-baseline.git \
TARGET_REVISION=feature/v0.4-aws-eks-baseline \
./scripts/deploy-aws-dev-root-app.sh
```

## 8. Validate Everything

```bash
./scripts/validate-all.sh
```

Manual checks:

```bash
kubectl get nodes
kubectl get applications -n argocd
kubectl get pods -A
kubectl get ingress -n startup-apps
```

## 9. Destroy

```bash
./scripts/destroy-aws-dev.sh
```

Delete Kubernetes-managed AWS resources before Terraform destroys the VPC.
