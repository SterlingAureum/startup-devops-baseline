# demo-api Release Evidence

This directory stores reviewed, machine-readable release qualification records.
Records are created only by the manual `demo-api release qualification evidence`
workflow and merged through a CODEOWNERS-protected pull request.

```text
evidence/demo-api/<source-environment>/<evidence-workflow-run-id>.json
```

An ordered promotion accepts a record only when it is passing, unexpired, uses
the v0.9.4 schema, names the requested source environment and workflow run, and
matches the current source release byte for byte. Evidence proves static release
schema, Helm rendering, and immutable GHCR artifact availability. It does not
claim that a test or production cluster exists, nor does it replace the runtime
rollout evidence introduced with v0.9.5.
