# Apply v0.9.2 Incremental Update

Base requirement: the repository must already contain the validated v0.9.1
Helm environment/release separation increment.

Use the patch from the repository root. It preserves the `clusters/aws-dev` to
`clusters/aws/base` file moves and removes the legacy paths correctly.

```bash
git status
git apply --check startup-devops-baseline-v0.9.2.patch
git apply startup-devops-baseline-v0.9.2.patch
```

The `overlay/` directory is included for file-by-file review. Do not use a
plain recursive copy as the only apply method because it cannot remove the old
`clusters/aws-dev` tree.

Run the required local validation:

```bash
./scripts/validate-aws-environment-declarations.sh
./scripts/validate-terraform.sh
./scripts/validate-ci-quality-gates.sh
```

The first validator requires either `kustomize` or `kubectl` for actual overlay
rendering. Terraform validation runs `fmt`, `init -backend=false`, and
`validate` for dev, test, and prod.

This checkpoint is declaration-only. Do not run `terraform apply` for aws-test
or aws-prod merely to accept v0.9.2, and do not copy dev state, Secrets, backup
objects, or database data into either environment.
