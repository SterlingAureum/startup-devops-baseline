# Environment inventory and identity boundary

`config/environments.example.yaml` is the versioned schema-1 template.
`--config FILE --env NAME` selects exactly one environment; CLI target overrides
take precedence and are validated again. show/dry-run read configuration only.
They do not resolve Git references, read remote state or validate live identities.

The inventory identifies the target and existing configuration locations:

- kind cluster, ports and bootstrap image; pinned Argo installer;
- GitOps repository, revision, root manifest/name and parent-chart Git parameters;
- future AWS expected account, region, profile/role reference;
- future Terraform root, variable-file and backend-file references.

The root manifest path is relative to the fetched Git repository, not to the
inventory file. The first version's Helm placeholders `${repository}` and
`${revision}` expand to the selected URL and resolved commit. Other parameter
strings are literal. Workload/service/probe settings belong in GitOps; VPC,
node and IAM resource definitions belong in Terraform. Avoid duplicating these
values in inventory. Future discovered endpoints should come from outputs.

Personal actual inventory belongs under
`~/.config/startup-devops-baseline/environments.yaml`; an optional
`config/environments.local.yaml` is Git-ignored. Shared enterprise non-secret
inventory can live in a private configuration repository. A deployment targeting
AWS does not require the operator's inventory to be stored on AWS: WSL, a bastion
or a CI runner reads it where the command executes.

Never put access/secret/session keys, GitHub tokens, passwords, private keys,
kubeconfig contents or Terraform state into inventory. Fixed-schema sections
reject unknown fields, including credential fields. This is not a secret scanner
for arbitrary user-provided strings; only non-secret GitOps parameters belong here.
Use AWS profiles/SSO on the workstation, workload roles on runners, and OIDC for CI.
Bootstrap authentication must work before any optional centralized config lookup.
If needed later, non-secret centralized parameters can use Parameter Store;
application secrets use the existing secret-management/GitOps integration.

The aws-dev/aws-test entries deliberately contain placeholder account IDs and
workstation file references. They currently support only:

```bash
python3 scripts/ops/cli.py show --env aws-dev
python3 scripts/ops/cli.py show --env aws-test
```

AWS lifecycle actions, including their dry-runs, fail explicitly before tools.
The inventory does not create IAM profiles or permissions. Future AWS execution
must resolve effective identities, compare the expected target account, separate
backend and infrastructure identities where necessary, and use reviewed plan/apply
and destroy flows. Existing restricted application runtime roles must not silently
become infrastructure provisioning roles. No IAM/state/backend change is included.
