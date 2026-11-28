# Terraform state foundation

Use this independent root to provision a shared, versioned state bucket. If your
team supplies the backend, configure the environment's private `.tfbackend`
directly. Routine environment teardown keeps the shared foundation.

## First installation in an empty account

From the repository root, use a fresh, dedicated checkout for the foundation.
The local backend override is private to this checkout. Use a durable private
directory for the bootstrap state and inputs. From subsequent shells, select
the same directory and state path.

```bash
umask 077
root=infra/terraform/aws/state-bootstrap
foundation_dir="$HOME/.local/state/startup-devops-baseline/state-bootstrap"
mkdir -p "$foundation_dir"
cp -n "$root/terraform.tfvars.example" "$foundation_dir/bootstrap.tfvars"
cp -n "$root/local_override.tf.example" "$root/local_override.tf"
```

Set the bucket name, region and tags in the private tfvars. The new-install
example selects SSE-S3. Select your AWS profile and check the caller account,
then run the following from the same shell.

```bash
aws sts get-caller-identity
terraform -chdir="$root" init -backend-config="path=$foundation_dir/bootstrap.tfstate"
terraform -chdir="$root" plan -var-file="$foundation_dir/bootstrap.tfvars" -out="$foundation_dir/create.tfplan"
terraform -chdir="$root" apply "$foundation_dir/create.tfplan"
terraform -chdir="$root" output -json backend_configuration
```

Back up the bootstrap state privately and retain its tfvars. For each environment,
copy its output values into its own private backend file and set
`allowed_account_ids` to your account. Its first apply writes state directly to S3.

To move the bootstrap state itself to S3 later, make a private backup, prepare a
private bootstrap backend file from the **bootstrap** output, then remove the
local override in the same initialized checkout. Run
`terraform -chdir="$root" init -migrate-state -backend-config=/absolute/path/bootstrap.tfbackend`.
Confirm the destination is the intended unused bootstrap key before accepting
the migration. Verify the resource list with `terraform -chdir="$root" state list`.

## Existing foundations and encryption

For an existing installation, reopen the original state with its existing
backend settings and private tfvars. Existing remote installations keep their
S3 backend declaration. Only the new-install example defaults to SSE-S3.
An existing installation that omits `state_encryption` continues to use its
managed KMS key. Terraform records address moves for the key and alias at index
zero. Review the plan for moves without deletion or replacement.

| state_encryption | Encryption and ownership |
| --- | --- |
| sse-s3 | S3-managed encryption. Backend output omits kms_key_id. |
| managed-kms | This root manages the key and alias and outputs the key ARN. |
| existing-kms | Supply existing_kms_key_arn. The key owner manages its lifecycle and policy. |

For a custom state layout, set individual paths in `state_key_overrides` (for
example `{ dev = "team-a/dev/terraform.tfstate" }`). The backend outputs and
per-root IAM policies use the same paths, including the matching lock objects.
Changing a path on an existing installation selects another object. Coordinate
state migration and permissions for both paths before applying an IAM change.
Keep separate environments on distinct bucket/key pairs.
