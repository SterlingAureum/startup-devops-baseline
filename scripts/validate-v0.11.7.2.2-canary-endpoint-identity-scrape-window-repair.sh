#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_DIR}"' EXIT

python3 - "${ROOT_DIR}" "${FIXTURE_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
fixture_dir = Path(sys.argv[2])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.2.2"
assert contract["predecessor"] == "v0.11.7.2.1"
assert all(contract["rootCause"].values())
assert all(contract["repairs"].values())
assert contract["timing"] == {
    "sloInitialDelay": "90s", "trafficDurationSeconds": 45,
    "trafficIntervalSeconds": 1, "prometheusScrapeInterval": "15s",
}
assert not any(contract["scope"].values())

chart = read("apps/demo-api/helm/Chart.yaml")
assert "version: 0.8.2" in chart and 'appVersion: "0.5.0"' in chart
values = read("apps/demo-api/helm/values.yaml")
slo = values.split("sloAware:", 1)[1]
assert "initialDelay: 90s" in slo

checker = read("scripts/check-local-slo-aware-rollout-analysis.sh")
for marker in (
    'TRAFFIC_DURATION_SECONDS="${TRAFFIC_DURATION_SECONDS:-45}"',
    'TRAFFIC_INTERVAL_SECONDS="${TRAFFIC_INTERVAL_SECONDS:-1}"',
    'CANARY_IDENTITY_WAIT_SECONDS="${CANARY_IDENTITY_WAIT_SECONDS:-120}"',
    "CANARY_IDENTITY_FIXTURE", "assert_canary_identity",
    "rollouts-pod-template-hash", "platform.startup.dev/release-id",
    "Waiting for canary Service endpoints", "traffic_started_at",
    "print_canary_identity_diagnostics",
): assert marker in checker, marker
assert checker.index("assert_canary_identity") < checker.index("port-forward service/demo-api-canary")
for forbidden in ("rollouts promote", "rollouts abort", "kubectl patch", "kubectl delete", "git push"):
    assert forbidden not in checker

expected = "demo-api-local-v0.11.7.2.2-fixture"
success = {
    "selectorHash": "newhash",
    "selectedPods": [{"name": "new-pod", "podTemplateHash": "newhash", "releaseId": expected, "ready": True}],
}
stale_release = {
    "selectorHash": "oldhash",
    "selectedPods": [{"name": "old-pod", "podTemplateHash": "oldhash", "releaseId": "demo-api-local-old", "ready": True}],
}
wrong_hash = {
    "selectorHash": "newhash",
    "selectedPods": [{"name": "wrong-hash", "podTemplateHash": "otherhash", "releaseId": expected, "ready": True}],
}
unready = {
    "selectorHash": "newhash",
    "selectedPods": [{"name": "unready", "podTemplateHash": "newhash", "releaseId": expected, "ready": False}],
}
empty = {"selectorHash": "newhash", "selectedPods": []}
for name, payload in (("success", success), ("stale", stale_release), ("wrong-hash", wrong_hash), ("unready", unready), ("empty", empty)):
    (fixture_dir / f"{name}.json").write_text(json.dumps(payload))

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair.sh"),
    ("README.md", "v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair"),
    ("CHANGELOG.md", "## v0.11.7.2.2"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.2.2 Endpoint identity, multi-scrape traffic, diagnostics, and boundary contracts passed.")
PY

EXPECTED_RELEASE_ID=demo-api-local-v0.11.7.2.2-fixture \
CANARY_IDENTITY_FIXTURE="${FIXTURE_DIR}/success.json" \
  "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" >/dev/null

for fixture in stale wrong-hash unready empty; do
  if EXPECTED_RELEASE_ID=demo-api-local-v0.11.7.2.2-fixture \
    CANARY_IDENTITY_FIXTURE="${FIXTURE_DIR}/${fixture}.json" \
      "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" >"${FIXTURE_DIR}/${fixture}.log" 2>&1; then
    echo "${fixture} canary identity fixture unexpectedly passed." >&2
    exit 1
  fi
  grep -F "canary Service still selects missing, unready, stale-hash, or wrong-release Pods" \
    "${FIXTURE_DIR}/${fixture}.log" >/dev/null
done

command -v helm >/dev/null 2>&1 || { echo "Required command not found: helm" >&2; exit 1; }
helm lint "${ROOT_DIR}/apps/demo-api/helm" >/dev/null
rendered="$(helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" --namespace startup-apps)"
grep -q 'helm.sh/chart: demo-api-0.8.2' <<<"${rendered}"
grep -q 'initialDelay: 90s' <<<"${rendered}"

bash -n \
  "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair.sh"

echo "v0.11.7.2.2 success, stale-release, wrong-hash, unready, empty, and Helm fixtures passed."
