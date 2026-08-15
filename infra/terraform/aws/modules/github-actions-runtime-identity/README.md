# GitHub Actions Runtime Access Identity

Maps one persistent, environment-isolated runtime IAM role into a live dev or
test EKS cluster through an access entry and the
`demo-api-runtime-qualification` Kubernetes group.

The IAM role and OIDC trust are owned separately by the account-bootstrap
`runtime-identities` root. Keeping only the access entry here means ordinary
environment destroy removes cluster access without deleting the role needed to
prove `environment_absent` before the next clean-room rebuild.

Matching namespaced Kubernetes Roles and RoleBindings are GitOps-managed from
`clusters/aws/base/security/runtime-qualification` in dev and test only. This
module does not create a runner, mutate a workload, grant access to Secrets, or
create any production identity.
