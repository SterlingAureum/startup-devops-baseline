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

This root deliberately remains local during v0.12.1 because the backend does
not exist before its first apply. Protect its local `terraform.tfstate` as a
sensitive, owner-readable artifact. v0.12.2 owns migration of that non-empty
state to `bootstrap/terraform.tfstate` after the backend exists.

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

The separately approved live plan/apply procedure is documented in
`docs/V0.12.1_REMOTE_STATE_FOUNDATION.md`. Do not initialize or migrate the
other four roots during v0.12.1.
