#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PY'
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
script = root / "scripts/check-v0.11.9.3.6.7.5-aws-test-recovery-root-plan.py"
spec = importlib.util.spec_from_file_location("recovery", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
contract = module.source_checks(root)
assert hashlib.sha256(script.read_bytes()).hexdigest() == (
    "05c3c01dc340d3257a7664dc93fd4dbb301da366dd4c3b062ce8590690a1aa82"
)
assert hashlib.sha256((root / module.CONTRACT).read_bytes()).hexdigest() == (
    "330aad260f0fe495159a12b5f45fcffab1dc25cacad40e83491ce95de8c94a09"
)
assert contract["version"] == "v0.11.9.3.6.7.5"
assert contract["implementationBaselineCommit"] == "0d281b630388ce61e88922f5244a3683e6a33687"
assert not any(contract["operationBoundary"].values())
assert contract["cost"]["historicalAwsTestSpendUsd"] is None
assert contract["cost"]["additionalBudgetLimitUsd"] == "8.00"
assert contract["cost"]["maximumNewWindowSeconds"] == 28800
assert contract["cost"]["minimumCleanupReserveSeconds"] == 3600
assert contract["cost"]["automaticBudgetEnforcement"] is False
assert contract["cost"]["automaticTeardown"] is False
assert contract["recovery"]["oldTemporaryPlanAndKubeconfigLost"] is True
assert contract["recovery"]["rawHistoricalEvidenceRecoverable"] is False
assert contract["rootDeploymentScope"]["directRootObjectIsNotWholeMutationScope"] is True
assert contract["rootDeploymentScope"]["credentialValueTransferRequiresSeparateApproval"] is True
assert contract["rootDeploymentScope"]["dnsReconciliationRequiresSeparateApproval"] is True
assert not hasattr(module, "execute")
source = script.read_text()
assert 'sub.add_parser("execute")' not in source
assert "get-secret-value" not in source
assert "GetSecretValue" not in source
assert '"terraform"' not in source
assert '"apply"' not in source
assert '"patch"' not in source
assert '"delete"' not in source
assert '"create"' not in source
for p in root.glob("scripts/*v0.11.9.3.6.7.5*.py"):
    ast.parse(p.read_text())
for name in ("inputs", "private-plan"):
    example = json.loads((root / f"delivery/contracts/v0.11.9.3.6.7.5-{name}.example.json").read_text())
    assert isinstance(example, dict)
plan = json.loads((root / "delivery/contracts/v0.11.9.3.6.7.5-private-plan.example.json").read_text())
assert all(value is None for value in plan["hourly_upper_bound_usd"].values())
assert not any(plan["reviewed_scope"].values())
assert plan["root_deployment_authorized"] is False
assert plan["additional_budget_limit_usd"] == "8.00"
print("v0.11.9.3.6.7.5 recovery evidence, scope, budget and no-execute contract passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.5-aws-test-recovery-root-plan.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.4.1.1-gitleaks-evidence-field-repair.sh"
echo "v0.11.9.3.6.7.5 passed; all checks offline, no live operation executed."
