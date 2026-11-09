# v0.9 Final Validation Evidence

The `final/` directory contains reviewed v0.9.6 closure records generated only
after the ephemeral aws-test environment has been exercised, destroyed, and
checked for residual AWS resources.

Each record references, but does not duplicate, the reviewed aws-dev runtime,
aws-test release, and aws-test runtime evidence. It stores SHA-256 hashes,
immutable artifact identity, ordered lifecycle timestamps, and the explicit
decision that aws-prod remained statically validated in v0.9.

Generate and validate a record with:

```bash
EVIDENCE_ACTOR=SterlingAureum \
DEV_RUNTIME_EVIDENCE_FILE=evidence/demo-api/runtime/aws-dev/<id>.json \
TEST_RELEASE_EVIDENCE_FILE=evidence/demo-api/aws-test/<run-id>.json \
TEST_RUNTIME_EVIDENCE_FILE=evidence/demo-api/runtime/aws-test/<id>.json \
FAILOVER_COMPLETED_AT=<UTC timestamp> \
TEST_DESTROY_COMPLETED_AT=<UTC timestamp> \
COST_AUDIT_COMPLETED_AT=<UTC timestamp> \
  ./scripts/write-v0.9-final-evidence.sh

EVIDENCE_FILE=evidence/v0.9/final/<id>.json \
  ./scripts/validate-v0.9-final-evidence.sh
```

Never store account identifiers, public management IPs, credentials, Secret
values, kubeconfig content, or raw Terraform state in this directory.
