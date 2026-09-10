#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6-reviewed-live-aws-test-promotion-handoff.json"
EVIDENCE="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.json"
RELEASE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-promote-environment.yaml"

python3 - "${CONTRACT}" "${WORKFLOW}" <<'PY'
import json
import pathlib
import sys

contract = json.loads(pathlib.Path(sys.argv[1]).read_text())
workflow = pathlib.Path(sys.argv[2]).read_text()
assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6"
assert contract["predecessor"] == "v0.11.9.3.6.5.2"
assert contract["implementationBaselineCommit"] == "5b592ac8958b4227048403bf1ff716f76f692b82"
assert contract["reviewedQualification"]["sha256"] == "a5994ebce978e55842dabe22cfbb6c48adcfaf61fa46503d06001a6cc3b2b92e"
assert contract["sourceRelease"]["sha256"] == "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
assert contract["sourceRelease"]["releaseId"] == "demo-api-cf0a6bcbc466-cdffd3d71763"
assert contract["targetRelease"]["currentSha256"] == "2817d5dbcb902b53956f564aa2024617249ee8e3cb003092bdf0724943342a91"
handoff = contract["workflowHandoff"]
assert handoff["qualificationMode"] == "reviewed-live-contract"
assert handoff["allowedEdge"] == "aws-dev->aws-test"
assert handoff["mutationScope"] == "target-release-only-pr"
assert handoff["exactProtectedMainRequired"] is True
assert handoff["automaticMerge"] is False
assert all(value is False for value in contract["operationBoundary"].values())
assert contract["executionAuthorized"] is False
for marker in (
    "reviewed-live-contract",
    "reviewed_live_contract_path",
    "reviewed_live_contract_sha256",
    "validate-reviewed-aws-dev-qualification-for-promotion.py",
    "aws-dev->aws-test",
):
    assert marker in workflow, marker
PY

test "$(sha256sum "${EVIDENCE}" | awk '{print $1}')" = \
  'a5994ebce978e55842dabe22cfbb6c48adcfaf61fa46503d06001a6cc3b2b92e'
test "$(sha256sum "${RELEASE}" | awk '{print $1}')" = \
  '5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46'

python3 "${ROOT_DIR}/scripts/test-v0.11.9.3.6.6-reviewed-live-promotion-handoff.py"
python3 "${ROOT_DIR}/scripts/validate-reviewed-aws-dev-qualification-for-promotion.py" \
  --evidence-contract "${EVIDENCE}" \
  --release-file "${RELEASE}" \
  --expected-contract-sha256 a5994ebce978e55842dabe22cfbb6c48adcfaf61fa46503d06001a6cc3b2b92e \
  --expected-release-sha256 5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46 \
  --expected-release-id demo-api-cf0a6bcbc466-cdffd3d71763

bash "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.sh"
bash "${ROOT_DIR}/scripts/validate-demo-api-promotion.sh"
bash "${ROOT_DIR}/scripts/validate-demo-api-promotion-governance.sh"
bash "${ROOT_DIR}/scripts/validate-reusable-delivery-stages.sh"
bash -n "${WORKFLOW}" 2>/dev/null || true
python3 -m py_compile \
  "${ROOT_DIR}/scripts/validate-reviewed-aws-dev-qualification-for-promotion.py" \
  "${ROOT_DIR}/scripts/test-v0.11.9.3.6.6-reviewed-live-promotion-handoff.py"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x "$0"
fi

echo "v0.11.9.3.6.6 reviewed live aws-dev-to-aws-test promotion handoff passed; no workflow, PR or live operation was executed."
