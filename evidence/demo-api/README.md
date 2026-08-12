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

v0.10.4 adds the durable, self-contained aws-dev Qualification Bundle. v0.10.5
extends the same reviewed format to aws-test:

```text
evidence/demo-api/qualification/aws-dev/<release-id>/<run-id>-<attempt>.json
evidence/demo-api/qualification/aws-test/<release-id>/<run-id>-<attempt>.json
```

It combines same-run static and trusted runtime results, their hashes, the
immutable release, and a deterministic environment-specific deployment-scope
hash. The
legacy v0.9 static/runtime records remain valid for the manual Promotion
Runbook, but they are not accepted as a substitute for the aws-dev Bundle in
the v0.10 automated path. Automated dev-to-test preparation accepts only the
merged aws-dev Bundle; aws-test qualification produces its own Bundle only
after the explicit reviewed Canary gate. v0.10.6 accepts that merged, fresh
aws-test Bundle as the sole automated source qualification for the reviewed
test-to-prod release PR. It does not create a prod Bundle or claim production
runtime qualification.
