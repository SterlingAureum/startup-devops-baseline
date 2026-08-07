# demo-api Release Evidence

This directory stores reviewed, machine-readable static release and AWS runtime
qualification records. Both record types are merged through a
CODEOWNERS-protected pull request.

```text
evidence/demo-api/<source-environment>/<evidence-workflow-run-id>.json
evidence/demo-api/runtime/<source-environment>/<UTC-YYYYMMDDHHMMSS>.json
```

An ordered promotion accepts a record only when it is passing, unexpired, uses
the v0.9.4 schema, names the requested source environment and workflow run, and
matches the current source release byte for byte. Evidence proves static release
schema, Helm rendering, and immutable GHCR artifact availability. It does not
claim that a test or production cluster exists.

Runtime records are collected with
`scripts/record-demo-api-runtime-evidence-aws.sh` from a clean `main` checkout
that exactly matches `origin/main` and can reach the restricted EKS endpoint.
They bind the current release bytes to Argo CD revision, workload identity,
ready digest-pinned Pods, public HTTPS health/readiness/version results and,
for aws-test/aws-prod, a Healthy Rollout, matching Successful AnalysisRun, and
completed ALB stable action. Runtime records expire after three days by
default. Promotion requires both record types to be reviewed on `main`.
