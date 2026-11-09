# demo-api chart

The chart deploys the demo workload, Services, telemetry wiring and optional
Rollout behavior. `values/environments/` holds environment settings and
`values/releases/` holds cloud release identity; neither directory moves in
this restructuring.

Current offline rendering from the repository root:

```bash
python3 scripts/delivery/flow.py render --environment local
python3 scripts/delivery/flow.py render --environment aws-dev
python3 scripts/delivery/flow.py render --environment aws-test
python3 scripts/delivery/flow.py render --environment aws-prod
```

Current kind lifecycle: [local workflow](../../../docs/operations/local.md).
Use its commit-tagged image build/deploy path. The local parent chart clears
`image.digest` for the explicit local-image override and provides the actual
source commit and application version. Otherwise a nonempty digest takes
precedence over a tag, as it should for cloud releases.

Cloud delivery uses a single built digest across environments. Demo-specific
HTTP/metrics validation remains an application adapter. Old delivery-evidence,
secret-rotation and rehearsal instructions are retained in
`archive/v0.12/entrypoint-notes/apps/demo-api/helm/README.md`; they are historical
references, not the current supported operator path.
