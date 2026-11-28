# Terraform state foundation

Use this independent root to provision a shared, versioned state bucket. If your
team supplies the backend, configure the environment's private `.tfbackend`
directly. Routine environment teardown keeps the shared foundation.

## First installation in an empty account

From the repository root, use a fresh, dedicated checkout for the foundation.
The root uses the local backend by default. Use a durable private
directory for the bootstrap state and inputs. From subsequent shells, select
the same directory and state path.

```bash
umask 077
root=infra/terraform/aws/state-bootstrap
foundation_dir="$HOME/.local/state/startup-devops-baseline/state-bootstrap"
mkdir -p "$foundation_dir"
cp -n "$root/terraform.tfvars.example" "$foundation_dir/bootstrap.tfvars"
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
private bootstrap backend file from the **bootstrap** output, and enable the S3
override in the same initialized checkout with
`cp "$root/s3_override.tf.example" "$root/s3_override.tf"`. Retire any older
local backend override in that checkout after checking its contents. Run
`terraform -chdir="$root" init -migrate-state -backend-config=/absolute/path/bootstrap.tfbackend`.
Confirm the destination is the intended unused bootstrap key before accepting
the migration. Verify the resource list with `terraform -chdir="$root" state list`.

## Existing foundations and encryption

For an existing installation, reopen the original state with its existing
backend settings and private tfvars. If bootstrap state already lives in S3, enable the override before the first
init on this version. In a fresh checkout, reconnect to the original bucket and key:

```bash
root=infra/terraform/aws/state-bootstrap
cp "$root/s3_override.tf.example" "$root/s3_override.tf"
terraform -chdir="$root" init -backend-config=/absolute/path/bootstrap.tfbackend
terraform -chdir="$root" state list
```

Verify the expected foundation resources before planning. Existing local
installations should continue to pass their original absolute state path to init.
The bucket provisioned by this root defaults to SSE-S3. Before planning an upgrade
of a foundation that created its own KMS key, set `state_encryption = "managed-kms"`
in the original private tfvars. Keep `existing-kms` and the original ARN when
using an external key. The managed key has `prevent_destroy`. An unexpected
plan to remove it stops planning. Restore the original selection and review
the plan for address moves without deletion or replacement.

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
