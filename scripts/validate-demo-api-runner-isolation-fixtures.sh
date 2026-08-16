#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from demo_api_runner_isolation import validate

repository = "SterlingAureum/startup-devops-baseline"
environment = "aws-dev"

def run(run_id, conclusion):
    return {
        "id": int(run_id),
        "path": ".github/workflows/demo-api-release-orchestrator.yaml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
    }

def jobs(runner_id, conclusion):
    return {
        "jobs": [{
            "name": "Qualify non-production from the trusted executor / Qualify aws-dev from a trusted executor",
            "labels": ["self-hosted", "linux", "x64", "trusted-runtime", "aws-dev"],
            "runner_id": runner_id,
            "runner_name": "aureum",
            "conclusion": conclusion,
        }]
    }

inputs = {
    "repository": repository,
    "environment": environment,
    "interrupted_run_id": "101",
    "resumed_run_id": "102",
    "interrupted_run": run("101", "cancelled"),
    "interrupted_jobs": jobs(21, "success"),
    "resumed_run": run("102", "success"),
    "resumed_jobs": jobs(22, "success"),
    "registered_runners": {"total_count": 0, "runners": []},
}

result = validate(**inputs)
if result["status"] != "passed" or result["interrupted"]["runnerId"] == result["resumed"]["runnerId"]:
    raise SystemExit("Positive runner isolation fixture failed.")

mutations = []
same_runner = deepcopy(inputs)
same_runner["resumed_jobs"] = jobs(21, "success")
mutations.append(("same runner_id", same_runner))

still_registered = deepcopy(inputs)
still_registered["registered_runners"] = {"total_count": 1, "runners": [{"id": 22, "name": "aureum"}]}
mutations.append(("runner still registered", still_registered))

wrong_run = deepcopy(inputs)
wrong_run["interrupted_run"]["conclusion"] = "success"
mutations.append(("interrupted run not cancelled", wrong_run))

wrong_labels = deepcopy(inputs)
wrong_labels["resumed_jobs"]["jobs"][0]["labels"].remove("aws-dev")
mutations.append(("environment label missing", wrong_labels))

for label, candidate in mutations:
    try:
        validate(**candidate)
    except ValueError:
        continue
    raise SystemExit(f"Unsafe runner isolation fixture was accepted: {label}")
PY

echo "demo-api runner isolation fixtures passed."
