#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT_DIR}/scripts/lib/argocd-operation.sh"

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
    require(value.get("schemaVersion") == "v0.11.3.3", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.3", "Bad version")
    require(
        value.get("status") == "offline-implemented-live-replay-required",
        "Bad implementation status",
    )
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    require(incident.get("application") == "startup-devops-root", "Wrong incident Application")
    require(incident.get("errorClass") == "FailedPrecondition", "Wrong error class")
    require(
        incident.get("errorMessage") == "another operation is already in progress",
        "Wrong operation-busy error",
    )
    require(incident.get("previousIdleObservationWasInsufficient") is True, "Old guard defect omitted")

    controls = value.get("controls", {})
    require(controls.get("sharedOperationHelper") == "scripts/lib/argocd-operation.sh", "Wrong helper")
    require(controls.get("boundedAttempts") == 5, "Retry bound changed")
    require(controls.get("retryDelaySeconds") == 2, "Retry delay changed")
    require(controls.get("stableIdleObservations") == 3, "Idle observation bound changed")
    require(controls.get("protectedMutations") == ["sync", "set", "unset"], "Mutation coverage changed")
    for key in (
        "busyErrorMatchedExactly",
        "featureAndRestorationUseSameHelper",
        "nonBusyErrorsFailImmediately",
        "exhaustionPrintsApplicationDiagnostics",
    ):
        require(controls.get(key) is True, f"Control disabled: {key}")

    dynamic = value.get("dynamicValidation", {})
    require(all(dynamic.values()), "Dynamic regression coverage disabled")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


contract = json.loads(read("delivery/contracts/v0.11.3.3-argocd-operation-race-hardening.json"))
validate_contract(contract)

helper = read("scripts/lib/argocd-operation.sh")
feature = read("scripts/deploy-local-feature-gitops.sh")
restore = read("scripts/restore-local-gitops-baseline.sh")

for marker in (
    "OPERATION_BUSY_MAX_ATTEMPTS",
    "OPERATION_RETRY_DELAY_SECONDS",
    "APPLICATION_IDLE_OBSERVATIONS",
    "another operation is already in progress",
    "run_argocd_mutation_with_retry",
    "argocd_application_diagnostics",
):
    require(marker in helper, f"Operation helper guard missing: {marker}")

for name, script in (("feature", feature), ("restore", restore)):
    require('source "${ROOT_DIR}/scripts/lib/argocd-operation.sh"' in script, f"{name} does not source helper")
    require("run_argocd_mutation_with_retry" in script, f"{name} does not use bounded retry")
    require("argocd app sync" in script, f"{name} sync path missing")

require("argocd app set" not in feature, "Feature returned to direct child set")
require("argocd app unset" not in feature, "Feature returned to direct child unset")
require("argocd app unset" not in restore, "Restore returned to direct child unset")
require(feature.count("run_argocd_mutation_with_retry") >= 1, "Feature sync retry coverage missing")
require(restore.count("run_argocd_mutation_with_retry") >= 1, "Restore sync retry coverage missing")

for name, mutate in (
    ("unbounded retry", lambda v: v["controls"].update(boundedAttempts=0)),
    ("non-busy retry", lambda v: v["controls"].update(nonBusyErrorsFailImmediately=False)),
    ("missing dynamic regression", lambda v: v["dynamicValidation"].update(transientBusyThenSuccess=False)),
    ("telemetry expansion", lambda v: v["boundaries"].update(applicationTelemetryChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.3.3 operation-race contract and static validation passed.")
PY

bash -n "${HELPER}"

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

export ARGOCD_NAMESPACE=argocd
export WAIT_TIMEOUT_SECONDS=3
export APPLICATION_IDLE_OBSERVATIONS=1
export OPERATION_BUSY_MAX_ATTEMPTS=3
export OPERATION_RETRY_DELAY_SECONDS=0

# shellcheck source=scripts/lib/argocd-operation.sh
source "${HELPER}"
validate_argocd_operation_settings

wait_for_application_idle() {
  printf '%s\n' "$1" >>"${WORK_DIR}/wait.log"
}

argocd_application_diagnostics() {
  printf '%s\n' "$1" >>"${WORK_DIR}/diagnostics.log"
}

next_attempt() {
  local counter_file="$1"
  local attempt=0
  if [ -f "${counter_file}" ]; then
    attempt="$(<"${counter_file}")"
  fi
  attempt=$((attempt + 1))
  printf '%s\n' "${attempt}" >"${counter_file}"
  printf '%s\n' "${attempt}"
}

transient_mutation() {
  local attempt
  attempt="$(next_attempt "${WORK_DIR}/transient.count")"
  if [ "${attempt}" -eq 1 ]; then
    echo "rpc error: code = FailedPrecondition desc = another operation is already in progress" >&2
    return 20
  fi
  echo "application.argoproj.io/test synced"
}

echo "==> Exercising transient operation-busy recovery"
transient_output="$(run_argocd_mutation_with_retry test-app transient_mutation 2>"${WORK_DIR}/transient.err")"
grep -q 'application.argoproj.io/test synced' <<<"${transient_output}"
grep -qx '2' "${WORK_DIR}/transient.count"
grep -qx 'test-app' "${WORK_DIR}/wait.log"
grep -q 'attempt 1/3' "${WORK_DIR}/transient.err"

permanent_mutation() {
  next_attempt "${WORK_DIR}/permanent.count" >/dev/null
  echo "rpc error: code = FailedPrecondition desc = another operation is already in progress" >&2
  return 20
}

echo "==> Exercising bounded permanent-busy failure"
if run_argocd_mutation_with_retry stuck-app permanent_mutation \
  >"${WORK_DIR}/permanent.out" 2>"${WORK_DIR}/permanent.err"; then
  echo "Permanent operation-busy mutation unexpectedly succeeded." >&2
  exit 1
fi
grep -qx '3' "${WORK_DIR}/permanent.count"
grep -qx 'stuck-app' "${WORK_DIR}/diagnostics.log"
grep -q 'remained operation-busy after 3 attempts' "${WORK_DIR}/permanent.err"

ordinary_failure() {
  next_attempt "${WORK_DIR}/ordinary.count" >/dev/null
  echo "rpc error: code = PermissionDenied desc = permission denied" >&2
  return 42
}

echo "==> Exercising immediate non-busy failure"
if run_argocd_mutation_with_retry denied-app ordinary_failure \
  >"${WORK_DIR}/ordinary.out" 2>"${WORK_DIR}/ordinary.err"; then
  echo "Non-busy mutation unexpectedly succeeded." >&2
  exit 1
fi
grep -qx '1' "${WORK_DIR}/ordinary.count"
grep -q 'PermissionDenied' "${WORK_DIR}/ordinary.err"

echo "==> Exercising invalid retry configuration rejection"
OPERATION_BUSY_MAX_ATTEMPTS=0
if validate_argocd_operation_settings >"${WORK_DIR}/invalid.out" 2>"${WORK_DIR}/invalid.err"; then
  echo "Invalid operation retry configuration was accepted." >&2
  exit 1
fi
grep -q 'OPERATION_BUSY_MAX_ATTEMPTS must be a positive integer' "${WORK_DIR}/invalid.err"

echo "v0.11.3.3 Argo CD operation race hardening validation passed."
