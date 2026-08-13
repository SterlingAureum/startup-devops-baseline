# v0.10 Final Acceptance Evidence

`final/` contains append-only v0.10 clean-room closure records generated only
after the complete protected-main dev/test/prod-static acceptance and both AWS
cost-cleanup audits pass.

Create a record with:

```bash
./scripts/write-v0.10-final-evidence.py \
  --input /tmp/v0.10-final-evidence-input.json \
  --output evidence/v0.10/final/<UTC timestamp>.json
```

Validate it with:

```bash
./scripts/validate-v0.10-final-evidence.py \
  --evidence evidence/v0.10/final/<UTC timestamp>.json
```

The record is evidence, not orchestration state. It must be added through a
reviewed evidence-only PR. Do not commit the operator input, AWS credentials,
kubeconfigs, endpoint addresses, logs containing secrets, or fabricated run
identities. See `docs/V0.10_FINAL_ACCEPTANCE_RUNBOOK.md`.
