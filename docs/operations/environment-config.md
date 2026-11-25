# Environment inventory and identity boundary

`config/environments.example.yaml` is the schema-2 template.
`--config FILE --env NAME` selects an exact inventory key. Every entry declares
a `driver` and a `delivery_environment`. The latter selects an exact key under
`environments` in this CLI checkout's `delivery/standard/config.json`. Its
`root_manifest` supplies the GitOps path for show, preflight and deployment.
Several inventory entries can select the same delivery target.

| Inventory key (example) | Driver | Delivery target | Infrastructure inputs |
| --- | --- | --- | --- |
| my-laptop | kind | local | Cluster name, ports and node image |
| sandbox | aws | aws-dev | Dev Terraform root, AWS account, region and backend |
| team-a-test | aws | aws-test | Test Terraform root, AWS account, region and backend |

Run `python3 scripts/ops/cli.py init-config` once. It creates
`~/.config/startup-devops-baseline/environments.yaml` with private permissions
and preserves an existing file. Everyday commands read this inventory by default.
Use `--config FILE` to select or initialize a different one. CI explicitly
selects the checked-in example.

Use `show --env NAME` and inspect `paths` for the resolved inventory, dedicated
kubeconfig and, for AWS, tfvars and backend input or state file. AWS connection
and lifecycle paths use the account, region and cluster name. When the personal
tfvars are missing the CLI reports the expected input path and leaves kubeconfig
unresolved. A reported path can precede creation of the file. The next dev deploy
writes the new connection and prints a kubectl command. An older `aws-dev.yaml`
can still be used for its original cluster until then.

The kind and AWS lifecycle drivers read shared Argo CD installation defaults
from `config/argocd-bootstrap.yaml` in the CLI checkout. Omit `argocd` to
follow that pin, or set `argocd.manifest` in an individual entry. Existing
explicit values continue to take precedence. For kind, `--argocd-manifest`
overrides the inventory value for that command. The standard installer uses
the `argocd` namespace. Inspect the effective settings before deployment:

```bash
python3 scripts/ops/cli.py show --env aws-dev | jq '.configuration.argocd'
```

**Update your personal inventory in place.**

1. Set the top-level `schema_version` to `2`.
2. Set `delivery_environment` beside `driver` for each entry, including entries
   named `local`, `aws-dev` and `aws-test`. Remove `gitops.root_manifest`
   from the inventory. Keep your Git repository, revision, root Application name
   and parameters. A fork using the standard root path can reuse the same target.
   For a different root layout, declare a delivery target in your fork's catalog.
3. Keep your AWS profiles, account IDs, regions, tfvars and state addresses.
   For a dev entry using `terraform.backend_file`, move its existing path to
   `terraform.backend.config_file` and set `terraform.backend.type: s3`.
   For a fresh test environment, set the backend type to `s3` and
   `config_file` to `aws-test.tfbackend`. Use the dedicated test key.
   Follow [AWS preparation](aws-transition.md#select-the-state-address) for prior local state.
4. Run `show` for each inventory key. Check `environment`, `driver`,
   `delivery_environment` and `gitops_root` before running `preflight`.
   These inventory edits do not migrate Terraform state.

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

For a kind entry, run the declaration check before choosing a Git revision.
Add `--check-inputs` to check the deployment tools on PATH, fetch the revision,
render the root chart and validate its child Applications. The command uses
temporary files and can run before the cluster exists. The JSON report on
stdout includes the resolved commit. Use that SHA with `up` to deploy exactly
what you checked. Preflight and up resolve the root through the same delivery target.

```bash
inventory="$HOME/.config/startup-devops-baseline/environments.yaml"
python3 scripts/ops/cli.py preflight --env local --config "$inventory"
python3 scripts/ops/cli.py preflight --env local --config "$inventory" --check-inputs --revision main
```

The aws-dev/aws-test entries deliberately contain placeholder account IDs and
workstation file references. Inspect the selected inventory or run offline preparation:

```bash
python3 scripts/ops/cli.py show --env aws-dev
python3 scripts/ops/cli.py preflight --env aws-test
```

Install the preflight dependencies and follow [AWS preparation](aws-transition.md) for private inputs.
Use the deploy command on a provisioned personal dev cluster. Terraform create, apply and destroy remain separate.
The inventory does not create IAM profiles or permissions. Future AWS execution
must resolve effective identities, compare the expected target account, separate
backend and infrastructure identities where necessary, and use reviewed plan/apply
and destroy flows. Existing restricted application runtime roles must not silently
become infrastructure provisioning roles.
