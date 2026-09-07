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

contract_path = "delivery/contracts/v0.11.7.3.1-final-rollout-convergence-wait-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.3.1"
assert contract["predecessor"] == "v0.11.7.3"
assert all(contract["rootCause"].values())
assert contract["repair"]["waitSeconds"] == 300
assert contract["repair"]["pollSeconds"] == 2
assert all(value for key, value in contract["repair"].items() if key not in {"waitSeconds", "pollSeconds"})
assert not any(contract["scope"].values())

closure = read("scripts/check-local-slo-progressive-delivery-closure.sh")
for marker in (
    'FINAL_ROLLOUT_WAIT_SECONDS="${FINAL_ROLLOUT_WAIT_SECONDS:-300}"',
    'FINAL_ROLLOUT_POLL_SECONDS="${FINAL_ROLLOUT_POLL_SECONDS:-2}"',
    "rollout_is_final_healthy", "print_final_rollout_diagnostics",
    "Rollout application version drifted while waiting",
    "Rollout did not converge on its Healthy stable ReplicaSet",
    "updatedReplicas", "pauseConditions",
): assert marker in closure, marker
assert closure.index("rollout_is_final_healthy") < closure.index("check-local-slo-burn-rate-alerts.sh")

version = "v0.11.7.3-accepted"
release_id = "demo-api-local-v0.11.7.3-accepted"
annotations = {
    "platform.startup.dev/application-version": version,
    "platform.startup.dev/release-id": release_id,
}
progressing = {
    "metadata": {"annotations": annotations}, "spec": {"replicas": 3},
    "status": {
        "phase": "Progressing", "currentStepIndex": 6,
        "currentPodHash": "newhash", "stableRS": "oldhash",
        "replicas": 5, "updatedReplicas": 3, "readyReplicas": 5,
        "availableReplicas": 5, "pauseConditions": None,
    },
}
healthy = {
    "metadata": {"annotations": annotations}, "spec": {"replicas": 3},
    "status": {
        "phase": "Healthy", "currentPodHash": "newhash", "stableRS": "newhash",
        "replicas": 3, "updatedReplicas": 3, "readyReplicas": 3,
        "availableReplicas": 3, "pauseConditions": None,
    },
}
drifted = json.loads(json.dumps(healthy))
drifted["metadata"]["annotations"]["platform.startup.dev/application-version"] = "v0.11.7.3-newer"
def analysis(name):
    return {
        "metadata": {"name": name},
        "spec": {"args": [{"name": "expected-release-id", "value": release_id}]},
        "status": {"phase": "Successful"},
    }
analysis_runs = {"items": [analysis("first"), analysis("second")]}
for name, payload in (("progressing", progressing), ("healthy", healthy), ("drifted", drifted), ("analysisruns", analysis_runs)):
    (fixture_dir / f"{name}.json").write_text(json.dumps(payload))

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.3.1-final-rollout-convergence-wait-repair.sh"),
    ("README.md", "v0.11.7.3.1-final-rollout-convergence-wait-repair"),
    ("CHANGELOG.md", "## v0.11.7.3.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.3.1 bounded wait, version lock, diagnostics, and unchanged-runtime contracts passed.")
PY

make_fake_kubectl() {
  local fake_dir="$1"
  local second_rollout="$2"
  mkdir -p "${fake_dir}"
  cp "${FIXTURE_DIR}/progressing.json" "${fake_dir}/progressing.json"
  cp "${FIXTURE_DIR}/${second_rollout}.json" "${fake_dir}/second.json"
  cp "${FIXTURE_DIR}/analysisruns.json" "${fake_dir}/analysisruns.json"
  cat >"${fake_dir}/kubectl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ " $* " == *" get rollout "* ]]; then
  count=0
  [ ! -f "${FAKE_KUBECTL_DIR}/count" ] || count="$(cat "${FAKE_KUBECTL_DIR}/count")"
  count=$((count + 1))
  printf '%s\n' "${count}" >"${FAKE_KUBECTL_DIR}/count"
  if [ "${count}" -eq 1 ]; then cat "${FAKE_KUBECTL_DIR}/progressing.json"; else cat "${FAKE_KUBECTL_DIR}/second.json"; fi
elif [[ " $* " == *" get analysisrun "* ]]; then
  cat "${FAKE_KUBECTL_DIR}/analysisruns.json"
else
  echo "unexpected fake kubectl arguments: $*" >&2
  exit 1
fi
SH
  chmod +x "${fake_dir}/kubectl"
}

make_fake_kubectl "${FIXTURE_DIR}/transition-bin" healthy
PATH="${FIXTURE_DIR}/transition-bin:${PATH}" \
FAKE_KUBECTL_DIR="${FIXTURE_DIR}/transition-bin" \
CLOSURE_PHASE=final \
EXPECTED_APPLICATION_VERSION=v0.11.7.3-accepted \
FINAL_ROLLOUT_WAIT_SECONDS=10 \
FINAL_ROLLOUT_POLL_SECONDS=0 \
RUN_FINAL_OBSERVABILITY_CHECKS=false \
  "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >"${FIXTURE_DIR}/transition.log"
grep -F "final local SLO and progressive-delivery closure passed" "${FIXTURE_DIR}/transition.log" >/dev/null
[ "$(cat "${FIXTURE_DIR}/transition-bin/count")" -eq 2 ]

make_fake_kubectl "${FIXTURE_DIR}/drift-bin" drifted
if PATH="${FIXTURE_DIR}/drift-bin:${PATH}" \
  FAKE_KUBECTL_DIR="${FIXTURE_DIR}/drift-bin" \
  CLOSURE_PHASE=final \
  EXPECTED_APPLICATION_VERSION=v0.11.7.3-accepted \
  FINAL_ROLLOUT_WAIT_SECONDS=10 \
  FINAL_ROLLOUT_POLL_SECONDS=0 \
  RUN_FINAL_OBSERVABILITY_CHECKS=false \
    "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >"${FIXTURE_DIR}/drift.log" 2>&1; then
  echo "Version-drift transition unexpectedly passed." >&2
  exit 1
fi
grep -F "Rollout application version drifted while waiting" "${FIXTURE_DIR}/drift.log" >/dev/null

bash -n \
  "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.7.3.1-final-rollout-convergence-wait-repair.sh"

echo "v0.11.7.3.1 Progressing-to-Healthy and version-drift transition fixtures passed."
