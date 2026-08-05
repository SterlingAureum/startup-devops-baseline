# Apply the v0.9.1 Increment

This package is based on the completed v0.9.0 main-convergence increment.

## Recommended: Git Patch

From the repository root, point `PATCH_FILE` at the extracted patch:

```bash
git status
git apply --check "${PATCH_FILE}"
git apply "${PATCH_FILE}"
git diff --check
```

The patch writes 35 target files and removes the former mixed values file:

```text
apps/demo-api/helm/values-aws-dev.yaml
```

## Alternative: Overlay

Copy the contents of `overlay/` into the repository root, preserving paths and
the executable bit on `scripts/validate-demo-api-values-separation.sh`. Then
delete the path listed in `DELETE_FILES.txt`.

## Validate

```bash
./scripts/validate-demo-api-values-separation.sh
./scripts/validate-ci-quality-gates.sh
```

This increment does not create aws-test or aws-prod clusters and does not make
AWS API calls during local validation.
