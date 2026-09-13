#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
import aws_test_immutable_root as h
c = h.source_checks(root)
assert hashlib.sha256((root / h.CONTRACT).read_bytes()).hexdigest() == "7ef6eba963f56508b97547eff24dc56bf75e84b48c8c4d4107a8f4ad28343e7e"
assert c["implementationBaselineCommit"] == "766498dbe6f305cb40e73b09328fd114dadcf6f7"
assert c["budget"]["totalLimitUsd"] == "36.00"
assert c["budget"]["expectedSpendTargetUsd"] == "20.00"
assert c["budget"]["cleanupCompleteByUtc"] == "2026-09-13T10:51:13Z"
assert c["budget"]["cleanupReserveSeconds"] == 5400
assert not c["budget"]["automaticTeardown"] and not c["capacity"]["billingHardCap"]
assert not any(c["operationBoundary"].values())
assert len(c["applications"]) == 18
for name in ("aws_test_immutable_root.py", "execute-v0.11.9.3.6.7.5.2-aws-test-root-deployment.py", "test-v0.11.9.3.6.7.5.2-aws-test-root-deployment.py"):
    ast.parse((root / "scripts" / name).read_text())
assert hashlib.sha256((root / ".gitleaksignore").read_bytes()).hexdigest() == "a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca"
print("v0.11.9.3.6.7.5.2 immutable source/budget/operation contract passed.")
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.5.2-aws-test-root-deployment.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.5.1-aws-test-root-capacity-cost.sh"
echo "v0.11.9.3.6.7.5.2 passed; tests performed no live operation."
