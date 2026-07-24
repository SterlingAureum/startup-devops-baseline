# Troubleshooting

## AWS Load Balancer Controller CrashLoopBackOff

### Symptoms

```text
unable to initialize AWS cloud
failed to get VPC ID
failed to fetch VPC ID from instance metadata
context deadline exceeded
```

### Cause

Worker nodes use IMDSv2 with hop limit `1`, so the controller Pod cannot discover the VPC through node metadata.

### Resolution

```bash
terraform -chdir=infra/terraform/aws/environments/dev output -raw vpc_id
```

Configure the returned value in `clusters/aws-dev/platform/aws-load-balancer-controller.yaml`:

```yaml
helm:
  values: |
    clusterName: startup-devops-baseline-dev
    region: us-east-1

    # Environment-specific infrastructure identifier.
    # Keep synchronized with Terraform output `vpc_id`.
    vpcId: vpc-xxxxxxxxxxxxxxxxx
```

Verify:

```bash
kubectl get deployment aws-load-balancer-controller -n kube-system \
  -o jsonpath='{.spec.template.spec.containers[0].args}'
echo
```

The args should include `--aws-vpc-id=...`.

The baseline intentionally keeps IMDS hop limit `1` rather than weakening node metadata isolation.

---

## Terraform Output Not Found

### Symptom

```text
Output "aws_load_balancer_controller_role_arn" not found
```

### Checks

```bash
grep -R "aws_load_balancer_controller_role_arn" infra/terraform/aws
terraform -chdir=infra/terraform/aws/environments/dev output
```

### Resolution

```bash
rm -f infra/terraform/aws/environments/dev/tfplan
terraform -chdir=infra/terraform/aws/environments/dev plan -out=tfplan
terraform -chdir=infra/terraform/aws/environments/dev apply tfplan
terraform -chdir=infra/terraform/aws/environments/dev output -raw aws_load_balancer_controller_role_arn
```

---

## No Pods in Default Namespace

`kubectl get pods` only checks `default`. Use:

```bash
kubectl get pods -A
```

Relevant namespaces include `argocd`, `kube-system`, and `startup-apps`.

---

## ALB Is Not Created

```bash
kubectl describe ingress demo-api -n startup-apps
kubectl logs -n kube-system deployment/aws-load-balancer-controller --tail=200
kubectl get serviceaccount aws-load-balancer-controller -n kube-system -o yaml
```

Confirm public subnets have `kubernetes.io/role/elb = 1`.

---

## Terraform Destroy Reports VPC Dependencies

Kubernetes-managed ALB resources may still exist. Use `./scripts/destroy-aws-dev.sh` instead of starting with direct Terraform destroy.
