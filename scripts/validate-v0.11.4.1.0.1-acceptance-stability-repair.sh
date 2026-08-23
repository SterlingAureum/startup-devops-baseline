#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Callable


root = Path(sys.argv[1])


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.1.0.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.1.0.1", "Bad version")
    require(value.get("predecessor") == "v0.11.4.1.0", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    discovery = value.get("podDiscovery", {})
    require(discovery.get("defaultTimeoutSeconds") == 30, "Pod discovery timeout changed")
    require(discovery.get("defaultRetrySeconds") == 2, "Pod discovery retry changed")
    for name in (
        "transientListErrorsRetried",
        "emptyResultsRetried",
        "lastApiErrorPreserved",
        "readyWaitStartsAfterDiscovery",
    ):
        require(discovery.get(name) is True, f"Pod discovery guarantee disabled: {name}")

    dashboard = value.get("observabilityDashboardConfigMap", {})
    require(dashboard.get("lookupMode") == "exact-name", "Dashboard lookup is not exact-name")
    require(dashboard.get("requiredLabel") == "grafana_dashboard=1", "Dashboard label changed")
    require(dashboard.get("labelVerifiedSeparately") is True, "Dashboard label is not verified")
    require(dashboard.get("nameAndSelectorCombined") is False, "Invalid name and selector accepted")

    baseline = value.get("baselineRestoration", {})
    require(baseline.get("preMergeRevision") == "immutable-feature-commit", "Pre-merge baseline changed")
    require(baseline.get("localImageOverridesRemoved") is True, "Local image overrides retained")
    require(baseline.get("rootAutomationRestored") is True, "Root automation not restored")
    require(baseline.get("postMergeRevision") == "remote-HEAD", "Post-merge baseline changed")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Repair boundary expanded")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


contract = json.loads(read("delivery/contracts/v0.11.4.1.0.1-acceptance-stability-repair.json"))
validate_contract(contract)

validate_source = read("scripts/validate.sh")
for marker in (
    'POD_DISCOVERY_TIMEOUT_SECONDS="${POD_DISCOVERY_TIMEOUT_SECONDS:-30}"',
    'POD_DISCOVERY_RETRY_SECONDS="${POD_DISCOVERY_RETRY_SECONDS:-2}"',
    'last_list_error="$list_output"',
    'pod discovery failed for selector',
    'after ${POD_DISCOVERY_TIMEOUT_SECONDS}s',
    'wait --for=condition=Ready pod -l "$selector"',
):
    require(marker in validate_source, f"validate.sh missing marker: {marker}")
require(
    '--no-headers 2>/dev/null | grep -q .' not in validate_source,
    "Silent single-attempt Pod discovery returned",
)

views_source = read("scripts/check-observability-views.sh")
for marker in (
    'GRAFANA_DASHBOARD_CONFIGMAP=',
    'get configmap "${GRAFANA_DASHBOARD_CONFIGMAP}"',
    "-o jsonpath='{.metadata.labels.grafana_dashboard}'",
    '[ "${dashboard_label}" = "1" ]',
):
    require(marker in views_source, f"observability check missing marker: {marker}")
require("-l grafana_dashboard=1" not in views_source, "Named ConfigMap still combines a selector")

for relative, required in (
    (
        "scripts/validate-ci-quality-gates.sh",
        "validate-v0.11.4.1.0.1-acceptance-stability-repair.sh",
    ),
    (
        ".github/CODEOWNERS",
        "/delivery/contracts/v0.11.4.1.0.1-acceptance-stability-repair.json @SterlingAureum",
    ),
    (
        ".github/CODEOWNERS",
        "/scripts/validate-v0.11.4.1.0.1-acceptance-stability-repair.sh @SterlingAureum",
    ),
    (
        ".github/CODEOWNERS",
        "/docs/V0.11.4.1.0.1_ACCEPTANCE_STABILITY_REPAIR.md @SterlingAureum",
    ),
):
    require(required in read(relative), f"{relative}: missing marker {required}")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("no list retry", lambda value: value["podDiscovery"].update(transientListErrorsRetried=False)),
    ("hidden API error", lambda value: value["podDiscovery"].update(lastApiErrorPreserved=False)),
    ("combined selector", lambda value: value["observabilityDashboardConfigMap"].update(nameAndSelectorCombined=True)),
    ("local override retained", lambda value: value["baselineRestoration"].update(localImageOverridesRemoved=False)),
    ("runtime expansion", lambda value: value["boundaries"].update(runtimeResourceChanged=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")
PY

python3 - "${ROOT_DIR}/scripts/validate.sh" "${WORK_DIR}/pod-discovery-function.sh" <<'PY'
from pathlib import Path
import sys


source = Path(sys.argv[1]).read_text()
start = source.index("wait_pods_ready_by_label() {")
end = source.index("\n\nwait_deployment_ready()", start)
Path(sys.argv[2]).write_text(source[start:end] + "\n")
PY

FAKE_STATE="${WORK_DIR}/state"
FAKE_MODE="recover"
export FAKE_STATE FAKE_MODE
mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [[ " $* " == *" get pods "* ]]; then
  count=0
  if [ -f "${FAKE_STATE}" ]; then
    count="$(cat "${FAKE_STATE}")"
  fi
  count=$((count + 1))
  printf '%s\n' "${count}" >"${FAKE_STATE}"

  case "${FAKE_MODE}" in
    recover)
      if [ "${count}" -eq 1 ]; then
        echo "temporary API transport error" >&2
        exit 1
      fi
      if [ "${count}" -eq 2 ]; then
        exit 0
      fi
      echo "coredns-test 1/1 Running 0 1m"
      ;;
    api-error)
      echo "persistent API transport error" >&2
      exit 1
      ;;
    empty)
      exit 0
      ;;
  esac
  exit 0
fi

if [[ " $* " == *" wait --for=condition=Ready pod "* ]]; then
  echo "wait" >>"${FAKE_STATE}.events"
  exit 0
fi

echo "unexpected fake kubectl arguments: $*" >&2
exit 1
SH
chmod +x "${WORK_DIR}/bin/kubectl"
PATH="${WORK_DIR}/bin:${PATH}"
export PATH

# shellcheck source=/dev/null
source "${WORK_DIR}/pod-discovery-function.sh"
PASS_MESSAGE=""
FAIL_MESSAGE=""
pass() { PASS_MESSAGE="$*"; }
fail() { FAIL_MESSAGE="$*"; }
TIMEOUT="5s"
POD_DISCOVERY_TIMEOUT_SECONDS=5
POD_DISCOVERY_RETRY_SECONDS=0

wait_pods_ready_by_label kube-system "k8s-app=kube-dns" CoreDNS
[ "${PASS_MESSAGE}" = "CoreDNS pods are Ready" ]
[ "$(cat "${FAKE_STATE}")" = "3" ]
[ "$(cat "${FAKE_STATE}.events")" = "wait" ]

FAKE_MODE="api-error"
export FAKE_MODE
printf '0\n' >"${FAKE_STATE}"
POD_DISCOVERY_TIMEOUT_SECONDS=0
FAIL_MESSAGE=""
if wait_pods_ready_by_label kube-system "k8s-app=kube-dns" CoreDNS; then
  echo "Persistent API error was accepted." >&2
  exit 1
fi
[[ "${FAIL_MESSAGE}" == *"pod discovery failed"*"persistent API transport error"* ]]

FAKE_MODE="empty"
export FAKE_MODE
printf '0\n' >"${FAKE_STATE}"
FAIL_MESSAGE=""
if wait_pods_ready_by_label kube-system "k8s-app=kube-dns" CoreDNS; then
  echo "Permanently empty selector was accepted." >&2
  exit 1
fi
[[ "${FAIL_MESSAGE}" == *"pods not found with selector"* ]]

echo "v0.11.4.1.0.1 acceptance stability repair validation passed."
