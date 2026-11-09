# State bootstrap root

This independent root declares the shared S3/KMS state foundation and exact-key
access policies. Existing Terraform declarations, lifecycle protections and
backend examples remain unchanged by repository restructuring.

The old staged bootstrap, migration and recovery procedures are historical
material under `archive/v0.12/`. They do not establish the current location or
identity of an operator's private state, and must not be run from relocated
paths. Resolve actual state ownership and location before planning any change.

Current backend-disabled static validation, from the repository root:

```bash
bash scripts/checks/terraform.sh
```

This does not migrate or recreate state. Shared state storage, KMS and retained
backend policies are not part of routine dev/test teardown.
