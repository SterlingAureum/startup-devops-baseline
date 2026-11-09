#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.4-aws-test-promotion-execution-evidence.json"

python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

import yaml

root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6.4"
assert contract["predecessor"] == "v0.11.9.3.6.6.3"
assert contract["protectedMainCommit"] == contract["promotion"]["mergeCommit"]
assert contract["promotion"]["pullRequestNumber"] == 91
assert contract["promotion"]["changedPaths"] == [
    "apps/demo-api/helm/values/releases/aws-test.yaml"
]
assert contract["promotion"]["checks"] == {
    "demoApiReleaseCurrentness": "success",
    "qualityGates": "success",
    "cancelled": 0,
    "failing": 0,
    "successful": 2,
    "skipped": 0,
    "pending": 0,
}

release = contract["release"]
dev = root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
test = root / "apps/demo-api/helm/values/releases/aws-test.yaml"
prod = root / "apps/demo-api/helm/values/releases/aws-prod.yaml"
assert dev.read_bytes() == test.read_bytes()
assert hashlib.sha256(dev.read_bytes()).hexdigest() == release["awsDevReleaseFileSha256"]
assert hashlib.sha256(test.read_bytes()).hexdigest() == release["awsTestReleaseFileSha256"]
assert hashlib.sha256(prod.read_bytes()).hexdigest() == release["awsProdReleaseFileSha256"]

values = yaml.safe_load(test.read_text())
assert values == {
    "image": {
        "repository": release["repository"],
        "tag": release["tag"],
        "digest": release["digest"],
    },
    "release": {"applicationVersion": release["applicationVersion"]},
    "delivery": {
        "sourceRepository": release["sourceRepository"],
        "sourceCommit": release["sourceCommit"],
        "workflowRunId": release["workflowRunId"],
    },
}

qualification = contract["qualificationEvidence"]
qualification_path = root / qualification["contractPath"]
assert hashlib.sha256(qualification_path.read_bytes()).hexdigest() == qualification["contractSha256"]
assert qualification["privateExecutionResultSha256"] == "2d56815b00bbcd050966b761828a093ee9fee7ab0aa63b15c77ebfa967c07d61"
assert qualification["boundedRequestCount"] == 54
assert qualification["runtimeQualified"] is True

boundaries = contract["boundaries"]
assert all(value is False for value in boundaries.values())
assert contract["nextAction"] == "review-separate-aws-dev-teardown-preflight"
PY

python3 -m json.tool "${CONTRACT}" >/dev/null
bash -n "$0"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0"; fi

echo "v0.11.9.3.6.6.4 aws-test promotion execution evidence passed; no live operation was executed."
