#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
path = root / "scripts/observe-v0.11.9.3.6.7.5.2.1-aws-test-cleanup.py"
spec = importlib.util.spec_from_file_location("observer", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.source_checks(root)
assert hashlib.sha256((root / m.CONTRACT).read_bytes()).hexdigest() == "5bdfd154c93ff79bab4bb5730ecd778d382f4173f7f06663e60523556d5afe4d"
assert c["version"] == c["schemaVersion"] == "v0.11.9.3.6.7.5.2.1"
assert c["implementationBaselineCommit"] == "375417830174723598a2565b8f197f74c2c50697"
assert c["executorExit"] == 0 and c["oneTimeApprovalConsumed"] is True
summary = c["executionSummary"]
raw = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
assert len(raw) == c["artifacts"]["executionResult"]["bytes"] == 821
assert hashlib.sha256(raw).hexdigest() == c["artifacts"]["executionResult"]["sha256"]
assert summary["reviewed_verify_sha256"] == c["artifacts"]["verificationResult"]["sha256"]
assert summary["root_manifest_sha256"] == c["artifacts"]["rootManifest"]["sha256"]
assert summary["control_plane_commit"] == c["implementationBaselineCommit"]
assert summary["root_health"] == summary["demo_application_health"] == "Healthy"
assert all(summary[key] for key in ("root_deployed", "database_ready", "credential_seeded_and_eso_verified", "dns_alias_insync", "terraform_state_unchanged"))
assert not any(summary[key] for key in ("traffic_generated", "qualification_executed", "automatic_retry_performed", "automatic_teardown_executed"))
assert c["budget"]["historicalBilledSpendUsd"] is None
assert c["budget"]["totalLimitUsd"] == "36.00" and c["budget"]["expectedSpendTargetUsd"] == "20.00"
assert c["budget"]["cleanupCompleteByUtc"] == c["cleanupPreparation"]["cleanupCompleteByUtc"] == "2026-09-13T10:51:13Z"
assert not c["cleanupPreparation"]["deletionAuthorized"]
assert not c["cleanupPreparation"]["legacyWrapperMayBeCalledDirectly"]
assert not c["cleanupPreparation"]["terraformDestroyPlanProduced"]
assert not any(c["privacyBoundary"].values()) and not any(c["packageProducer"].values())
assert not c["approvalScope"]["teardownApproved"]
assert c["artifacts"]["executionStderr"]["sha256"] == hashlib.sha256(b"").hexdigest()
for artifact in c["artifacts"].values():
    assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
for name in (path, root / "scripts/test-v0.11.9.3.6.7.5.2.1-aws-test-cleanup-observer.py"):
    ast.parse(name.read_text())
for name in (root / m.CONTRACT, root / "docs/V0.11.9.3.6.7.5.2.1_AWS_TEST_ROOT_EXECUTION_EVIDENCE_AND_CLEANUP.md"):
    text = name.read_text()
    for forbidden in ("/home/sterling/", "arn:aws:", "secretMetadataSha256", "AKIA"):
        assert forbidden not in text, (name, forbidden)
    assert re.search(r"(?<![a-zA-Z0-9])[0-9]{12}(?![a-zA-Z0-9])", text) is None
    assert re.search(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32", text) is None
assert hashlib.sha256((root / ".gitleaksignore").read_bytes()).hexdigest() == "a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca"
print("v0.11.9.3.6.7.5.2.1 exact execution/source/privacy/cleanup boundary passed.")
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.5.2.1-aws-test-cleanup-observer.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.5.2-aws-test-immutable-root-deployment.sh"
echo "v0.11.9.3.6.7.5.2.1 passed; all validation offline."
