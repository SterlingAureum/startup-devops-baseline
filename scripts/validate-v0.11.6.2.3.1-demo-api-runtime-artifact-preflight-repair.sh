#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])

def read(relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Missing file: {relative}")
    return path.read_text()

contract_path = "delivery/contracts/v0.11.6.2.3.1-demo-api-runtime-artifact-preflight-repair.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.6.2.3.1"
    assert value["predecessor"] == "v0.11.6.2.3"
    assert not any(value["scope"][key] for key in (
        "applicationCodeChanged", "helmDesiredStateChanged",
        "runtimeComponentAdded", "awsRuntimeChanged",
    ))
    assert all(value["repair"][key] for key in (
        "neutralReplayImageRejected", "singleRuntimeImageIdRequired",
        "allReadyPodsInspected", "structuredLoggingModuleRequired",
        "tracingModuleRequired", "tracingEnvironmentRequired",
    ))
    assert value["repair"]["lokiTimeoutExtended"] is False
    assert value["acceptance"]["freshUniqueImageRequired"] is True
    assert value["acceptance"]["realCorrelationRuns"] == 2
    assert value["incident"]["classification"] == "runtime-artifact-provenance-drift"
    assert value["incident"]["securityVulnerability"] is False
    assert value["incident"]["gitOpsHealthySufficient"] is False
    assert value["incident"]["knownNeutralImageTag"] == "sha-3e50802"

validate(contract)
assert (root / contract["designDocument"]).is_file()
assert (root / "delivery/contracts/v0.11.6.2.3-local-minimal-tracing-closure.json").is_file()

live = read("scripts/check-local-tracing-end-to-end.sh")
for marker in (
    'NEUTRAL_IMAGE_TAG="${NEUTRAL_IMAGE_TAG:-sha-3e50802}"',
    'still uses neutral replay image',
    'unique_image_ids',
    '.status.containerStatuses',
    'import inspect, os, src.logging_config, src.main, src.server, src.tracing',
    '"configure_logging()" in server',
    '"configure_tracing()" in server',
    'os.environ.get("TRACING_ENABLED", "").lower() == "true"',
    'two independent real trace-log correlations',
):
    assert marker in live, marker
assert live.count('check-local-demo-api-trace-correlation.sh"') == 2
for forbidden in (
    "QUERY_TIMEOUT_SECONDS=180", "kubectl delete", "rollout restart",
    "imagePullPolicy: Always",
):
    assert forbidden not in live, forbidden

guide = read(contract["designDocument"])
for marker in (
    "runtime artifact provenance drift", "sha-3e50802",
    "build-load-demo-api-image.sh", "deploy-local-feature-gitops.sh",
    "immutable digest", "not a Loki, Gateway, DNS, Tempo, or security vulnerability",
):
    assert marker in guide, marker

for mutate in (
    lambda value: value["scope"].update(applicationCodeChanged=True),
    lambda value: value["repair"].update(lokiTimeoutExtended=True),
    lambda value: value["acceptance"].update(freshUniqueImageRequired=False),
    lambda value: value["incident"].update(gitOpsHealthySufficient=True),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden runtime-artifact repair mutation was accepted")

print("v0.11.6.2.3.1 runtime artifact identity preflight and negative contracts passed.")
PY
