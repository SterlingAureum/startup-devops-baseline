# GitHub Actions Runtime Identity

Creates one non-production, environment-isolated IAM role and EKS access
entry for trusted runtime qualification. The role accepts only the exact
GitHub Environment OIDC subject for this repository, can describe only the
target EKS cluster, and maps into the
`demo-api-runtime-qualification` Kubernetes group.

The account-level `token.actions.githubusercontent.com` OIDC provider is an
input because it is shared account infrastructure and must not be duplicated
by disposable dev and test roots. The matching namespaced Kubernetes Roles
and RoleBindings are GitOps-managed from
`clusters/aws/base/security/runtime-qualification` in dev and test only.

The module does not create a runner, mutate a cluster workload, grant access
to Secrets, or create any production identity.
