#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
script = root / "scripts/review-v0.11.9.3.6.7.5.1-aws-test-root-cost.py"
spec = importlib.util.spec_from_file_location("cost", script)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.source_checks(root)
assert hashlib.sha256(script.read_bytes()).hexdigest() == "c57456e83dada7226e7a0565d02851abc1702336b1e6edbb25fbf87cde9428b6"
assert hashlib.sha256((root / m.CONTRACT).read_bytes()).hexdigest() == "d4b8900af6cfd2e86d84a3552e8b08e110a8c9ee1e79d0463bf7ae3b16fe8ecf"
assert c["implementationBaselineCommit"] == "a5a934b7208804f7ec693ca401a130628b06f31a"
assert c["historicalSpendUsd"] is None and c["additionalBudgetLimitUsd"] == "8.00"
assert not any(c["operationBoundary"].values())
assert c["costRules"]["limitsAreBillingHardCaps"] is False
assert c["revisionPolicy"]["immutableCascadeImplementationComplete"] is False
assert sum(p["configured_node_limit"] for p in c["nodePools"]) == 10
assert sum(p["cpu_limit"] for p in c["nodePools"]) == 20
for pool in c["nodePools"]:
    text = (root / pool["path"]).read_text()
    assert re.search(r"name: " + re.escape(pool["name"]) + r"\s", text)
    assert re.search(r"limits:\s+cpu: \"" + str(pool["cpu_limit"]) + r"\"\s+memory: " + pool["memory_limit"] + r"\s+nodes: " + str(pool["configured_node_limit"]) + r"\s", text)
    assert pool["root_disk_gib"] == 30
for name in ("karpenter-ec2nodeclass.yaml", "karpenter-ec2nodeclass-fis.yaml", "karpenter-ec2nodeclass-database.yaml"):
    assert "volumeSize: 30Gi" in (root / "clusters/aws/base/platform" / name).read_text()
cnpg = (root / "clusters/aws/base/data-platform/postgresql/cluster.yaml").read_text()
assert "instances: 3" in cnpg and "size: 20Gi" in cnpg
assert "enablePodAntiAffinity: true" in cnpg and "podAntiAffinityType: required" in cnpg
monitoring = (root / "clusters/aws/base/platform/monitoring.yaml").read_text()
assert "storage: 2Gi" in monitoring and "storage: 10Gi" in monitoring
example = m.prior.load(root / "delivery/contracts/v0.11.9.3.6.7.5.1-cost-profile.example.json")
assert all(v["usd"] is None for v in example["rates"].values())
assert all(v["usd"] is None for v in example["pool_node_hourly_upper_usd"].values())
assert example["fixed_and_uncertainty_reserve_usd"] is None
source = script.read_text()
for p in root.glob("scripts/*v0.11.9.3.6.7.5.1*.py"):
    ast.parse(p.read_text())
assert not hasattr(m, "execute")
for forbidden in ("subprocess", "os.system", "prior.observe(", 'add_parser("execute")', "put-secret-value", "get-secret-value"):
    assert forbidden not in source
assert hashlib.sha256((root / ".gitleaksignore").read_bytes()).hexdigest() == "a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca"
print("v0.11.9.3.6.7.5.1 capacity/source/cost/no-live-operation contract passed.")
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.5.1-aws-test-root-cost.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.5-aws-test-recovery-root-design.sh"
echo "v0.11.9.3.6.7.5.1 passed; all validation offline."
