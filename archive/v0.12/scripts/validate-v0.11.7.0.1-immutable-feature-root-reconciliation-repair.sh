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

contract_path = "delivery/contracts/v0.11.7.0.1-immutable-feature-root-reconciliation-repair.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.7.0.1"
    assert value["predecessor"] == "v0.11.7.0"
    assert value["scope"]["environment"] == "local"
    assert not any(value["scope"][key] for key in (
        "sloFormulaChanged", "dashboardChanged", "alertRuleChanged",
        "rolloutChanged", "runtimeResourceChanged", "applicationImageChanged",
        "awsRuntimeChanged",
    ))
    assert all(value["repair"][key] for key in (
        "localHeadCompared", "remoteFeatureHeadCompared",
        "rootTargetRevisionCompared", "rootChildRevisionParameterCompared",
        "namespaceGuardrailsRevisionCompared", "demoApiRevisionCompared",
        "observabilityViewsRevisionCompared", "targetAndStatusRevisionRequired",
        "existingImageReuseCommandPrinted",
    ))
    assert value["repair"]["childDirectPatchRecommended"] is False
    assert value["acceptance"]["rootRedeployRequiredAfterEachCommittedIncrement"] is True
    assert value["acceptance"]["syncedHealthyAloneSufficient"] is False
    assert value["acceptance"]["hardRefreshAloneSufficient"] is False
    assert value["incident"]["classification"] == "immutable-feature-root-not-advanced"
    assert value["incident"]["runtimeDefect"] is False

validate(contract)
assert (root / contract["designDocument"]).is_file()
assert (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()

live = read("scripts/check-local-slo-foundation.sh")
for marker in (
    'FEATURE_REVISION="${FEATURE_REVISION:-feature/v0.11-observability-sre-baseline}"',
    'git -C "${ROOT_DIR}" rev-parse HEAD',
    'git ls-remote "${REPOSITORY_URL}" "refs/heads/${FEATURE_REVISION}"',
    "startup-devops-root namespace-guardrails demo-api observability-views",
    "Application/${application_name} targetRevision",
    "Application/${application_name} status revision",
    "git.targetRevision parameter",
    "deploy-local-feature-gitops.sh",
    "IMAGE_REPOSITORY=${image_repository}",
    "IMAGE_TAG=${image_tag}",
    "APPLICATION_VERSION=${application_version}",
):
    assert marker in live, marker
revision_check = live.index("==> Checking immutable feature Root and child revision alignment")
resource_check = live.index("==> Checking GitOps ownership and SLO resources")
assert revision_check < resource_check
for forbidden in (
    "kubectl patch application observability-views",
    "argocd.argoproj.io/refresh=hard",
    "rollout restart", "IMAGE_PULL_POLICY=Always",
):
    assert forbidden not in live, forbidden

guide = read(contract["designDocument"])
for marker in (
    "Synced", "f95581d", "2375fd6", "immutable commit",
    "does not automatically advance", "Reuse the already accepted demo-api image",
    "Do not patch child", "deploy-local-feature-gitops.sh",
):
    assert marker in guide, marker

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.0.1-immutable-feature-root-reconciliation-repair.sh"),
    ("README.md", "v0.11.7.0.1-immutable-feature-root-reconciliation-repair"),
    ("docs/OBSERVABILITY.md", "v0.11.7.0.1"),
    ("docs/ROADMAP.md", "v0.11.7.0.1"),
    ("CHANGELOG.md", "## v0.11.7.0.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

for mutate in (
    lambda value: value["scope"].update(sloFormulaChanged=True),
    lambda value: value["repair"].update(remoteFeatureHeadCompared=False),
    lambda value: value["repair"].update(childDirectPatchRecommended=True),
    lambda value: value["acceptance"].update(syncedHealthyAloneSufficient=True),
    lambda value: value["acceptance"].update(hardRefreshAloneSufficient=True),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden feature-Root reconciliation mutation was accepted")

print("v0.11.7.0.1 immutable feature Root revision alignment and recovery contracts passed.")
PY

WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/git" <<'SH'
#!/usr/bin/env bash
case "$*" in
  *"remote get-url origin"*) echo "https://example.invalid/startup-devops-baseline.git" ;;
  *"rev-parse HEAD"*) echo "f95581d0795fe057d4a955ce915d0857231d5cd9" ;;
  *"ls-remote"*) printf '%s\t%s\n' "f95581d0795fe057d4a955ce915d0857231d5cd9" "refs/heads/feature/v0.11-observability-sre-baseline" ;;
  *) echo "UNMATCHED FAKE GIT: $*" >&2; exit 2 ;;
esac
SH

cat >"${WORK_DIR}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
case "$*" in
  *"get application startup-devops-root"*".spec.source.targetRevision"*)
    echo -n "2375fd62244a8e0f26bf0cb9b88a67c8ffe3a435"
    ;;
  *"get application startup-devops-root namespace-guardrails demo-api observability-views"*)
    echo "startup-devops-root 2375fd6 Synced Healthy 2375fd6"
    ;;
  *"get rollout demo-api"*".image}"*)
    echo -n "startup-devops-baseline/demo-api:v0.11.6.2.3.1-f95581d-local"
    ;;
  *"get rollout demo-api"*"APP_VERSION"*)
    echo -n "v0.11.6.2.3.1-f95581d-local"
    ;;
  *) echo "UNMATCHED FAKE KUBECTL: $*" >&2; exit 2 ;;
esac
SH
chmod +x "${WORK_DIR}/bin/git" "${WORK_DIR}/bin/kubectl"

set +e
PATH="${WORK_DIR}/bin:${PATH}" \
FEATURE_REVISION="feature/v0.11-observability-sre-baseline" \
REPOSITORY_URL="https://example.invalid/startup-devops-baseline.git" \
  "${ROOT_DIR}/scripts/check-local-slo-foundation.sh" \
  >"${WORK_DIR}/stale-root.out" 2>&1
fixture_status="$?"
set -e

[ "${fixture_status}" -ne 0 ] || {
  echo "Stale immutable Root fixture unexpectedly passed." >&2
  exit 1
}
for marker in \
  "Application/startup-devops-root targetRevision" \
  "expected f95581d0795fe057d4a955ce915d0857231d5cd9" \
  "found 2375fd62244a8e0f26bf0cb9b88a67c8ffe3a435" \
  "IMAGE_TAG=v0.11.6.2.3.1-f95581d-local" \
  "./scripts/deploy-local-feature-gitops.sh"; do
  grep -Fq "${marker}" "${WORK_DIR}/stale-root.out" || {
    echo "Stale Root fixture output is missing: ${marker}" >&2
    cat "${WORK_DIR}/stale-root.out" >&2
    exit 1
  }
done

echo "v0.11.7.0.1 stale immutable Root negative fixture passed."
