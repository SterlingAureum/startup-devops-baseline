# AWS Terraform baseline

The modules and five roots remain at their existing paths: `state-bootstrap`,
`runtime-identities`, `environments/dev`, `environments/test` and
`environments/prod`. This restructuring does not change Terraform resources,
backend keys or state locations. Root names are configuration identities, not
proof that a live environment currently exists.

From the repository root, with Terraform installed:

```bash
bash scripts/checks/terraform.sh
```

This checks tracked-file formatting, initializes each root with its backend
disabled, and validates configuration. It downloads providers when needed but
does not contact a state backend or run plan/apply/destroy.

Current AWS apply/bootstrap/destroy tooling is being redesigned. Previous
commands and operator notes are preserved under `archive/v0.12/`; they are
historical references, not relocated executable entrypoints. See
[the transition boundary](../../../docs/operations/aws-transition.md).

Keep credentials, private tfvars, plans and state outside Git. Review account,
region, environment, backend and data-retention policy before any real operation.
State-backend retirement is separate from disposable environment deletion.
