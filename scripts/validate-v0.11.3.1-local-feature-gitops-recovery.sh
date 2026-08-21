#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


def validate_contract(value: dict, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.3.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.1", "Bad version")
    require(value.get("status") == "offline-implemented-live-recovery-observed", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    require(incident.get("failedRevision") == 14, "Failed revision evidence changed")
    require(incident.get("recoveredRevision") == 15, "Recovered revision evidence changed")
    require(incident.get("recoveredRolloutPhase") == "Healthy", "Recovery was not Healthy")
    require(incident.get("recoveredAnalysisPhase") == "Successful", "Analysis did not succeed")
    require(incident.get("analysisMeasurements") == 2, "Unexpected analysis measurement count")
    require(incident.get("retryCommandCausedRecovery") is False, "Wrong retry command is credited with recovery")
    require("retry rollout demo-api" in incident.get("correctRetryCommand", ""), "Correct retry syntax missing")

    causes = value.get("causes", {})
    require(all(causes.get(key) is True for key in causes), "A recovered cause is not recorded")

    controls = value.get("controls", {})
    expected_allowlist = ["image.pullPolicy", "image.repository", "image.tag", "release.applicationVersion"]
    require(controls.get("featureHelmParameterAllowlist") == expected_allowlist, "Bad Helm parameter allowlist")
    for key in (
        "manualRootRenderedBeforeCreateOrApply",
        "applicationOperationIdleWait",
        "applicationOperationSerialization",
        "childAutomationPausedDuringMutation",
        "unexpectedHelmParametersExplicitlyUnset",
        "restorationRemovesAllLiveHelmParameters",
        "restorationAssertsEmptyHelmParameterSet",
        "rootAutomationRestoredLast",
    ):
        require(controls.get(key) is True, f"Control disabled: {key}")

    boundaries = value.get("boundaries", {})
    require(all(boundaries.get(key) is False for key in boundaries), "Patch boundary expanded")


contract = json.loads(read("delivery/contracts/v0.11.3.1-local-feature-gitops-recovery.json"))
validate_contract(contract)

root_deploy = read("scripts/deploy-root-app.sh")
feature = read("scripts/deploy-local-feature-gitops.sh")
restore = read("scripts/restore-local-gitops-head.sh")
operation_helper = read("scripts/lib/argocd-operation.sh")

for marker in ("SYNC_MODE_FILE", "if [ \"${ROOT_SYNC_MODE}\" = \"manual\" ]", "automated:/,/^    syncOptions:"):
    require(marker in root_deploy, f"Root manual-render guard missing: {marker}")

for marker in (
    'source "${ROOT_DIR}/scripts/lib/argocd-operation.sh"',
    "run_argocd_mutation_with_retry",
    "remove_unexpected_demo_parameters",
    "argocd app unset",
    "demo-api local Helm parameter allowlist",
    "set_application_automation \"${DEMO_APP_NAME}\" manual",
    "kubectl argo rollouts retry rollout",
):
    require(marker in feature, f"Feature recovery guard missing: {marker}")
require("kubectl argo rollouts retry ${DEMO_APP_NAME}" not in feature, "Invalid retry syntax returned")

for marker in ("wait_for_application_idle", "argocd app wait", "--operation"):
    require(marker in operation_helper, f"Shared operation guard missing: {marker}")

for marker in (
    "ROOT_SYNC_MODE=manual",
    "remove_all_demo_parameters",
    "argocd app unset",
    "still has live Helm parameters",
    "set_application_automation \"${ROOT_APP_NAME}\" automated",
):
    require(marker in restore, f"Restore recovery guard missing: {marker}")
require(
    restore.index("remove_all_demo_parameters") < restore.index("set_application_automation \"${ROOT_APP_NAME}\" automated"),
    "Root automation is restored before parameter cleanup",
)

for name, mutate in (
    ("retry credited", lambda v: v["incident"].update(retryCommandCausedRecovery=True)),
    ("idle wait disabled", lambda v: v["controls"].update(applicationOperationIdleWait=False)),
    ("stale parameter cleanup disabled", lambda v: v["controls"].update(unexpectedHelmParametersExplicitlyUnset=False)),
    ("telemetry mutation", lambda v: v["boundaries"].update(applicationTelemetryChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.3.1 local feature GitOps recovery validation passed.")
PY

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORK_DIR}/bin"
cat >"${WORK_DIR}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
if [ "${1:-}" = "get" ] && [ "${2:-}" = "namespace" ]; then
  exit 0
fi
if [ "${1:-}" = "apply" ] && [ "${2:-}" = "-f" ]; then
  cp "${3}" "${CAPTURED_ROOT_MANIFEST}"
  exit 0
fi
exit 0
SH
chmod +x "${WORK_DIR}/bin/kubectl"

echo "==> Exercising Root manual/automated render boundary with a fake kubectl"
TEST_REVISION="feature/test"
(
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/manual.yaml" \
  TARGET_REVISION="${TEST_REVISION}" \
  ROOT_SYNC_MODE=manual \
    ./scripts/deploy-root-app.sh >/dev/null
)

if grep -q '^    automated:' "${WORK_DIR}/manual.yaml"; then
  echo "Manual Root render retained automated sync." >&2
  exit 1
fi
grep -q '^    syncOptions:' "${WORK_DIR}/manual.yaml"
grep -q "^    targetRevision: ${TEST_REVISION}$" "${WORK_DIR}/manual.yaml"

(
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/automated.yaml" \
  TARGET_REVISION=HEAD \
  ROOT_SYNC_MODE=automated \
    ./scripts/deploy-root-app.sh >/dev/null
)
grep -q '^    automated:' "${WORK_DIR}/automated.yaml"

echo "v0.11.3.1 Root render behavior validation passed."
