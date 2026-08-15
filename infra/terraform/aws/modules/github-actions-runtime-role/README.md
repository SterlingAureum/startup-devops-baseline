# GitHub Actions Runtime Role

Creates one persistent, non-production IAM role for trusted runtime
qualification. It accepts only the exact repository and GitHub Environment
OIDC subject and permits only `sts:GetCallerIdentity` plus
`eks:DescribeCluster` for one deterministic cluster ARN.

The module deliberately has no dependency on a live EKS cluster. It belongs to
the account-bootstrap `runtime-identities` Terraform root so a clean-room
workflow can distinguish an absent cluster from an OIDC failure before a
disposable dev or test environment is created.

The environment-owned EKS access entry is separate and remains in
`github-actions-runtime-identity`. Neither module creates a runner, grants
production access, or writes Kubernetes.
