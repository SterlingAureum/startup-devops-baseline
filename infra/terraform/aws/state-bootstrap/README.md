# Terraform State Bootstrap

This independent Terraform root declares the shared S3/KMS remote-state
foundation without depending on an EKS environment. It creates:

- one versioned, bucket-owner-enforced S3 bucket;
- complete S3 public-access blocking and a TLS-only bucket policy;
- one rotation-enabled customer-managed KMS key and alias;
- five exact state keys with S3-native `.tflock` companions; and
- one unattached least-privilege IAM policy per Terraform root.

The S3 bucket and KMS key use `prevent_destroy`; the bucket also uses
`force_destroy = false`. Removing those controls is a separately reviewed
decommission action, never a normal environment teardown.

## Bootstrap state

This root deliberately remains local because the backend did not exist before
its first apply. The reviewed apply used a private staged source rather than a
repository-root state file. Protect both its private
`source/terraform.tfstate` and byte-identical preserved apply copy as sensitive,
owner-readable artifacts. v0.12.2.0.1 binds those private artifacts as the
future migration source and cross-check; it does not activate the backend or
authorize migration.

## Access boundary

The root creates managed IAM policies but attaches none of them. Policy
attachment is an explicit access-grant decision; application delivery and the
existing GitHub runtime roles receive no Terraform state authority from this
increment. S3 permissions are exact-key scoped. Only each key's `.tflock`
object receives `s3:DeleteObject`; the corresponding state object does not.

## Validation

Offline validation performs no Terraform initialization or AWS call:

```bash
bash scripts/validate-v0.12.1-remote-state-foundation.sh
```

The guarded plan-only entry point is documented in
`docs/V0.12.1.1_GUARDED_STATE_BOOTSTRAP_PLAN.md`. It stages an exact private
source copy and initializes only that copy with `-backend=false`. Plan
execution still needs separate approval, and a successful plan cannot be
applied until the v0.12.1.2 reviewed saved-plan checkpoint. Do not initialize
or migrate the other four roots. v0.12.2.1 owns the first private bootstrap
migration preflight.
