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
    require(value.get("schemaVersion") == "v0.11.3.6", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.6", "Bad version")
    require(
        value.get("status") == "offline-implemented-full-quality-gate-required",
        "Bad status",
    )
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    require(
        incident.get("failedValidator") == "scripts/validate-namespace-guardrails.sh",
        "Wrong failed validator",
    )
    require(
        incident.get("staleExpectedPath")
        == "clusters/local/platform/namespace-guardrails.yaml",
        "Wrong stale path",
    )
    require(
        incident.get("currentTemplatePath")
        == "clusters/local/platform/templates/namespace-guardrails.yaml",
        "Wrong template path",
    )
    require(incident.get("migrationIntroducedBy") == "v0.11.3.4", "Wrong migration")
    require(incident.get("runtimeResourceMissing") is False, "Runtime resource incorrectly missing")
    require(incident.get("legacyFileMustBeRestored") is False, "Legacy file restoration accepted")

    namespace = value.get("namespaceGuardrailValidation", {})
    require(
        namespace.get("stableValuesPath") == "clusters/local/platform/values.yaml",
        "Wrong stable values path",
    )
    for key in (
        "templatePathChecked",
        "templatedRepositoryValueChecked",
        "templatedRevisionValueChecked",
        "stableHeadValueChecked",
        "legacyRawApplicationRejected",
        "awsMainContractRetained",
    ):
        require(namespace.get(key) is True, f"Namespace validation disabled: {key}")

    admission = value.get("admissionPolicyValidation", {})
    require(admission.get("localPlatformScan") == "recursive", "Local scan is not recursive")
    for key in (
        "nestedTemplatesCovered",
        "strictLocalDigestApplicationRejected",
        "tagLoadedLocalImageBoundaryRetained",
    ):
        require(admission.get(key) is True, f"Admission validation disabled: {key}")

    require(all(value.get("dynamicValidation", {}).values()), "Dynamic validation disabled")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


contract = json.loads(read("delivery/contracts/v0.11.3.6-helm-migration-validator-coverage.json"))
validate_contract(contract)

namespace_validator = read("scripts/validate-namespace-guardrails.sh")
admission_validator = read("scripts/validate-application-admission-policies.sh")

for marker in (
    'local_app = local_platform / "templates" / "namespace-guardrails.yaml"',
    'local_values = local_platform / "values.yaml"',
    'legacy_local_app = local_platform / "namespace-guardrails.yaml"',
    "repoURL: {{ .Values.git.repoURL | quote }}",
    "targetRevision: {{ .Values.git.targetRevision | quote }}",
    "targetRevision: HEAD",
    "Legacy raw local namespace guardrail Application must not coexist",
):
    require(marker in namespace_validator, f"Namespace migration guard missing: {marker}")

require('local_platform.rglob("*.yaml")' in admission_validator, "Recursive local scan missing")
require('local_platform.glob("*.yaml")' not in admission_validator, "Shallow local scan remains")
for validator in (namespace_validator, admission_validator):
    require("VALIDATION_ROOT_DIR" in validator, "Negative-fixture root override missing")

for name, mutate in (
    ("legacy raw Application accepted", lambda v: v["namespaceGuardrailValidation"].update(legacyRawApplicationRejected=False)),
    ("shallow admission scan", lambda v: v["admissionPolicyValidation"].update(localPlatformScan="shallow")),
    ("nested policy accepted", lambda v: v["admissionPolicyValidation"].update(nestedTemplatesCovered=False)),
    ("runtime resource mutation", lambda v: v["boundaries"].update(namespaceGuardrailResourceChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.3.6 Helm migration validator coverage contract and static validation passed.")
PY

echo "==> Running corrected namespace guardrail validation"
"${ROOT_DIR}/scripts/validate-namespace-guardrails.sh"

echo "==> Running corrected application admission-policy validation"
"${ROOT_DIR}/scripts/validate-application-admission-policies.sh"

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORK_DIR}/repository"
cp -a \
  "${ROOT_DIR}/platform" \
  "${ROOT_DIR}/clusters" \
  "${ROOT_DIR}/scripts" \
  "${WORK_DIR}/repository/"

echo "==> Rejecting a reintroduced raw local namespace guardrail Application"
: >"${WORK_DIR}/repository/clusters/local/platform/namespace-guardrails.yaml"
if VALIDATION_ROOT_DIR="${WORK_DIR}/repository" \
  "${ROOT_DIR}/scripts/validate-namespace-guardrails.sh" \
  >"${WORK_DIR}/legacy.out" 2>"${WORK_DIR}/legacy.err"; then
  echo "Reintroduced raw namespace guardrail Application was accepted." >&2
  exit 1
fi
grep -q 'Legacy raw local namespace guardrail Application must not coexist' "${WORK_DIR}/legacy.err"
rm -f -- "${WORK_DIR}/repository/clusters/local/platform/namespace-guardrails.yaml"

echo "==> Rejecting a nested local strict admission-policy Application"
: >"${WORK_DIR}/repository/clusters/local/platform/templates/application-admission-policies.yaml"
if VALIDATION_ROOT_DIR="${WORK_DIR}/repository" \
  "${ROOT_DIR}/scripts/validate-application-admission-policies.sh" \
  >"${WORK_DIR}/nested.out" 2>"${WORK_DIR}/nested.err"; then
  echo "Nested local strict admission-policy Application was accepted." >&2
  exit 1
fi
grep -q 'Strict digest admission must remain disabled for tag-loaded local images' "${WORK_DIR}/nested.err"

echo "v0.11.3.6 Helm migration validator coverage validation passed."
