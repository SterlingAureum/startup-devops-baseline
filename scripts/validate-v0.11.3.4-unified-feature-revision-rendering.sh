#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
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
    require(value.get("schemaVersion") == "v0.11.3.4", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.4", "Bad version")
    require(value.get("status") == "offline-implemented-live-replay-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    source = value.get("sourceModel", {})
    require(source.get("platformChart") == "clusters/local/platform", "Wrong platform Chart")
    require(source.get("platformChartVersion") == "0.1.0", "Wrong platform Chart version")
    require(
        source.get("sameRepositoryApplications")
        == ["startup-devops-root", "namespace-guardrails", "demo-api"],
        "Same-repository Application set changed",
    )
    require(source.get("sameRepositoryRevisionValue") == "git.targetRevision", "Wrong revision value")
    require(source.get("stableRevision") == "HEAD", "Stable revision changed")
    require(source.get("externalChartVersionsRemainIndependent") is True, "External versions coupled")

    feature = value.get("featureInput", {})
    require(feature.get("operatorInput") == "TARGET_REVISION", "Wrong feature input")
    require(feature.get("resolvedForm") == "full-40-character-commit-sha", "Mutable revision accepted")
    for key in (
        "remoteBranchResolvedOnce",
        "localCommitMustMatchRemote",
        "trackedWorkingTreeMustBeClean",
        "rootAndChildrenUseResolvedCommit",
    ):
        require(feature.get(key) is True, f"Feature guard disabled: {key}")

    rendering = value.get("rootRendering", {})
    require(rendering.get("rootSyncMode") == "manual", "Feature Root is not manual")
    require(len(rendering.get("parameters", [])) == 7, "Root parameter set changed")
    require(rendering.get("directChildSetOrUnsetRequired") is False, "Direct child mutation returned")
    require(rendering.get("expectedRootSyncStatus") == "Synced", "Root drift remains expected")
    require(rendering.get("rootResyncSafeDuringFeatureValidation") is True, "Root resync remains unsafe")

    require(
        value.get("externalCharts")
        == {"argo-rollouts": "2.41.0", "ingress-nginx": "4.11.3", "monitoring": "88.5.0"},
        "External Chart version changed",
    )

    restoration = value.get("restoration", {})
    require(restoration.get("rootRevision") == "HEAD", "Root restoration changed")
    require(restoration.get("childRevisionValue") == "HEAD", "Child restoration changed")
    require(restoration.get("localImageEnabled") is False, "Local image remains enabled")
    require(restoration.get("demoApiParametersRenderedExplicitlyEmpty") is True, "Empty parameters not rendered")
    require(restoration.get("directChildCleanupRequired") is False, "Imperative cleanup returned")
    require(restoration.get("rootAutomationRestored") is True, "Root automation not restored")
    require(restoration.get("expectedRootSyncStatus") == "Synced", "Restored Root drift accepted")

    require(all(value.get("dynamicValidation", {}).values()), "Dynamic validation disabled")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


contract = json.loads(read("delivery/contracts/v0.11.3.4-unified-feature-revision-rendering.json"))
validate_contract(contract)

chart = read("clusters/local/platform/Chart.yaml")
observability_successor = (root / "delivery/contracts/v0.11.4.0-grafana-recording-rules.json").is_file()
controller_metrics_successor = (root / "delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json").is_file()
alertmanager_successor = (root / "delivery/contracts/v0.11.5.0-alertmanager-foundation.json").is_file()
alert_lifecycle_drill_successor = (root / "delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json").is_file()
values = read("clusters/local/platform/values.yaml")
root_app = read("clusters/local/root-app.yaml")
feature = read("scripts/deploy-local-feature-gitops.sh")
restore_head = read("scripts/restore-local-gitops-head.sh")
restore_feature = read("scripts/restore-local-feature-baseline.sh")
restore = read("scripts/restore-local-gitops-baseline.sh")
root_deploy = read("scripts/deploy-root-app.sh")
revision_helper = read("scripts/lib/git-revision.sh")

chart_markers = (
    "name: startup-devops-local-platform",
    "version: 0.4.1" if alert_lifecycle_drill_successor else ("version: 0.4.0" if alertmanager_successor else ("version: 0.3.0" if controller_metrics_successor else ("version: 0.2.0" if observability_successor else "version: 0.1.0"))),
    'appVersion: "v0.11.5.2.0"' if alert_lifecycle_drill_successor else ('appVersion: "v0.11.5.0"' if alertmanager_successor else ('appVersion: "v0.11.4.1.0"' if controller_metrics_successor else ('appVersion: "v0.11.4.0"' if observability_successor else 'appVersion: "v0.11.3.4"'))),
)
for marker in chart_markers:
    require(marker in chart, f"Platform Chart marker missing: {marker}")

for marker in (
    "targetRevision: HEAD",
    "enabled: false",
    "version: 2.41.1" if controller_metrics_successor else "version: 2.41.0",
    "version: 4.11.3",
    "version: 88.5.0",
):
    require(marker in values, f"Stable platform value missing: {marker}")

template_paths = {
    "argo-rollouts": "clusters/local/platform/templates/argo-rollouts.yaml",
    "ingress-nginx": "clusters/local/platform/templates/ingress-nginx.yaml",
    "monitoring": "clusters/local/platform/templates/monitoring.yaml",
    "namespace-guardrails": "clusters/local/platform/templates/namespace-guardrails.yaml",
    "demo-api": "clusters/local/platform/templates/demo-api.yaml",
}
for name, relative in template_paths.items():
    text = read(relative)
    require(f"name: {name}" in text, f"Wrong Application template: {relative}")
    require("feature/v0.11" not in text, f"Feature revision committed: {relative}")

for relative in (
    "clusters/local/platform/templates/namespace-guardrails.yaml",
    "clusters/local/platform/templates/demo-api.yaml",
):
    text = read(relative)
    require(".Values.git.repoURL" in text, f"Shared repository value missing: {relative}")
    require(".Values.git.targetRevision" in text, f"Shared revision value missing: {relative}")

demo_template = read("clusters/local/platform/templates/demo-api.yaml")
for marker in (
    ".Values.demoApi.localImage.enabled",
    "image.repository",
    "image.tag",
    "image.pullPolicy",
    "release.applicationVersion",
    "parameters: []",
):
    require(marker in demo_template, f"demo-api Root ownership missing: {marker}")

for relative in (
    "clusters/local/platform/argo-rollouts.yaml",
    "clusters/local/platform/ingress-nginx.yaml",
    "clusters/local/platform/monitoring.yaml",
    "clusters/local/platform/namespace-guardrails.yaml",
    "clusters/local/platform/demo-api.yaml",
):
    require(not (root / relative).exists(), f"Legacy raw Application remains: {relative}")

for marker in (
    "helm:",
    "git.repoURL",
    "git.targetRevision",
    "demoApi.localImage.enabled",
    "demoApi.localImage.applicationVersion",
):
    require(marker in root_app, f"Root Helm input missing: {marker}")
require("directory:" not in root_app, "Root still treats the platform Chart as a raw directory")
require(re.search(r"^    targetRevision: HEAD$", root_app, re.MULTILINE) is not None, "Stable Root HEAD missing")
root_parameter_names = re.findall(r"^        - name: (\S+)$", root_app, re.MULTILINE)
require(
    root_parameter_names
    == [
        "git.repoURL",
        "git.targetRevision",
        "demoApi.localImage.enabled",
        "demoApi.localImage.repository",
        "demoApi.localImage.tag",
        "demoApi.localImage.pullPolicy",
        "demoApi.localImage.applicationVersion",
    ],
    "Root Helm parameter allowlist changed",
)

for marker in (
    "GIT_TARGET_REVISION",
    "LOCAL_IMAGE_ENABLED",
    "demoApi.localImage.enabled",
    "IMAGE_PULL_POLICY",
):
    require(marker in root_deploy, f"Root renderer input missing: {marker}")

for marker in (
    'source "${ROOT_DIR}/scripts/lib/git-revision.sh"',
    "resolve_remote_git_revision",
    "git rev-parse HEAD",
    "git diff --quiet",
    'GIT_TARGET_REVISION="${resolved_target_revision}"',
    "LOCAL_IMAGE_ENABLED=true",
    "Root declaratively owns the exact child commit",
    "A Root resync is safe",
):
    require(marker in feature, f"Feature unification guard missing: {marker}")
for forbidden in ("argocd app set", "argocd app unset", "remove_unexpected_demo_parameters"):
    require(forbidden not in feature, f"Imperative feature child mutation returned: {forbidden}")

for marker in (
    'GIT_TARGET_REVISION="${TARGET_REVISION}"',
    "LOCAL_IMAGE_ENABLED=false",
    'sync_application_if_needed "${ROOT_APP_NAME}"',
    'sync_application_if_needed "${DEMO_APP_NAME}"',
    'set_application_automation "${ROOT_APP_NAME}"',
    "Root did not remain Synced",
):
    require(marker in restore, f"Declarative restoration guard missing: {marker}")
require("TARGET_REVISION=HEAD" in restore_head, "Post-merge HEAD wrapper changed")
require("resolve_remote_git_revision" in restore_feature, "Feature baseline is not immutable")
for forbidden in ("argocd app set", "argocd app unset", "remove_all_demo_parameters"):
    require(forbidden not in restore, f"Imperative restoration returned: {forbidden}")

for marker in ("git ls-remote --exit-code", "refs/heads/${requested_revision}", "full commit SHA"):
    require(marker in revision_helper, f"Remote revision guard missing: {marker}")

for name, mutate in (
    ("mutable feature", lambda v: v["featureInput"].update(resolvedForm="branch")),
    ("direct child mutation", lambda v: v["rootRendering"].update(directChildSetOrUnsetRequired=True)),
    ("Root drift", lambda v: v["rootRendering"].update(expectedRootSyncStatus="OutOfSync")),
    ("external Chart coupling", lambda v: v["sourceModel"].update(externalChartVersionsRemainIndependent=False)),
    ("production expansion", lambda v: v["boundaries"].update(productionAutomationChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.3.4 unified feature revision contract and static validation passed.")
PY

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORK_DIR}/bin"
cat >"${WORK_DIR}/bin/git" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
  ls-remote)
    printf '%s\t%s\n' 'fedcba9876543210fedcba9876543210fedcba98' 'HEAD'
    ;;
  fetch|cat-file)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
SH
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
chmod +x "${WORK_DIR}/bin/git" "${WORK_DIR}/bin/kubectl"

FEATURE_SHA="0123456789abcdef0123456789abcdef01234567"

echo "==> Exercising unified manual feature Root render"
(
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/feature-root.yaml" \
  TARGET_REVISION="${FEATURE_SHA}" \
  GIT_TARGET_REVISION="${FEATURE_SHA}" \
  ROOT_SYNC_MODE=manual \
  LOCAL_IMAGE_ENABLED=true \
  IMAGE_REPOSITORY=startup-devops-baseline/demo-api \
  IMAGE_TAG=v0.11.3-local \
  IMAGE_PULL_POLICY=Never \
  APPLICATION_VERSION=v0.11.3-local \
    ./scripts/deploy-root-app.sh >/dev/null
)

echo "==> Exercising automated stable Root render"
(
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/stable-root.yaml" \
  TARGET_REVISION=HEAD \
  GIT_TARGET_REVISION=HEAD \
  ROOT_SYNC_MODE=automated \
  LOCAL_IMAGE_ENABLED=false \
    ./scripts/deploy-root-app.sh >/dev/null
)

python3 - "${WORK_DIR}/feature-root.yaml" "${WORK_DIR}/stable-root.yaml" "${FEATURE_SHA}" <<'PY'
from pathlib import Path
import re
import sys


feature = Path(sys.argv[1]).read_text()
stable = Path(sys.argv[2]).read_text()
sha = sys.argv[3]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_revision(text: str) -> str:
    match = re.search(r"^    targetRevision:\s*\"?([^\"\s]+)\"?\s*$", text, re.MULTILINE)
    require(match is not None, "Root source revision missing")
    return match.group(1)


def parameter(text: str, name: str) -> str:
    pattern = rf"^        - name: {re.escape(name)}\n          value: \"([^\"]*)\"$"
    match = re.search(pattern, text, re.MULTILINE)
    require(match is not None, f"Root parameter missing: {name}")
    return match.group(1)


require(source_revision(feature) == sha, "Feature Root source is not the resolved SHA")
require(parameter(feature, "git.targetRevision") == sha, "Feature child value is not the resolved SHA")
require(parameter(feature, "demoApi.localImage.enabled") == "true", "Feature image mode is disabled")
require(parameter(feature, "demoApi.localImage.tag") == "v0.11.3-local", "Feature image tag changed")
require(re.search(r"^    automated:", feature, re.MULTILINE) is None, "Feature Root remained automated")

require(source_revision(stable) == "HEAD", "Stable Root source changed")
require(parameter(stable, "git.targetRevision") == "HEAD", "Stable child value changed")
require(parameter(stable, "demoApi.localImage.enabled") == "false", "Stable local image enabled")
require(re.search(r"^    automated:", stable, re.MULTILINE) is not None, "Stable Root automation missing")

print("v0.11.3.4 Root render behavior validation passed.")
PY

echo "==> Exercising invalid Root input rejection"
if (
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/invalid-root.yaml" \
  TARGET_REVISION="${FEATURE_SHA}" \
  GIT_TARGET_REVISION="${FEATURE_SHA}" \
  ROOT_SYNC_MODE=manual \
  LOCAL_IMAGE_ENABLED=true \
  IMAGE_TAG='' \
    ./scripts/deploy-root-app.sh
) >"${WORK_DIR}/invalid.out" 2>"${WORK_DIR}/invalid.err"; then
  echo "Invalid local-image Root input was accepted." >&2
  exit 1
fi
grep -q 'IMAGE_TAG and APPLICATION_VERSION are required' "${WORK_DIR}/invalid.err"

cat >"${WORK_DIR}/bin/git" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
if [ "${1:-}" = "ls-remote" ] && [ "${4:-}" = "refs/heads/feature/test" ]; then
  printf '%s\t%s\n' 'abcdefabcdefabcdefabcdefabcdefabcdefabcd' 'refs/heads/feature/test'
  exit 0
fi
exit 2
SH
chmod +x "${WORK_DIR}/bin/git"

echo "==> Exercising immutable remote branch resolution"
resolved="$(
  (
  PATH="${WORK_DIR}/bin:${PATH}"
  source "${ROOT_DIR}/scripts/lib/git-revision.sh"
  resolve_remote_git_revision example.invalid/repository.git feature/test
  )
)"
if [ "${resolved}" != "abcdefabcdefabcdefabcdefabcdefabcdefabcd" ]; then
  echo "Remote branch did not resolve to the expected SHA." >&2
  exit 1
fi

echo "==> Exercising missing remote branch rejection"
if (
  PATH="${WORK_DIR}/bin:${PATH}"
  source "${ROOT_DIR}/scripts/lib/git-revision.sh"
  resolve_remote_git_revision example.invalid/repository.git feature/missing
) >"${WORK_DIR}/missing.out" 2>"${WORK_DIR}/missing.err"; then
  echo "Missing remote branch was accepted." >&2
  exit 1
fi
grep -q 'remote Git revision not found' "${WORK_DIR}/missing.err"

mkdir -p "${WORK_DIR}/feature-bin"
cat >"${WORK_DIR}/feature-bin/git" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
  ls-remote)
    printf '%s\t%s\n' '0123456789abcdef0123456789abcdef01234567' 'refs/heads/feature/test'
    ;;
  rev-parse)
    printf '%s\n' '0123456789abcdef0123456789abcdef01234567'
    ;;
  diff)
    exit 0
    ;;
  fetch|cat-file)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
SH
cat >"${WORK_DIR}/feature-bin/argocd" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
SH
cat >"${WORK_DIR}/feature-bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail

sha='0123456789abcdef0123456789abcdef01234567'
prometheus='http://observability-metrics-prometheus.observability.svc.cluster.local:9090'

if [ "${1:-}" = "get" ] && [ "${2:-}" = "namespace" ]; then
  exit 0
fi
if [ "${1:-}" = "apply" ] && [ "${2:-}" = "-f" ]; then
  cp "${3}" "${CAPTURED_ROOT_MANIFEST}"
  exit 0
fi

if [ "${1:-}" = "-n" ]; then
  shift 2
fi

if [ "${1:-}" = "patch" ]; then
  exit 0
fi
if [ "${1:-}" != "get" ]; then
  exit 0
fi

resource="${2:-}"
name="${3:-}"
output=''
for ((index = 1; index <= $#; index++)); do
  if [ "${!index}" = "-o" ]; then
    next=$((index + 1))
    output="${!next}"
    break
  fi
done

case "${resource}:${output}" in
  application:*'.operation}'*)
    exit 0
    ;;
  application:*'.status.operationState.phase}'*)
    printf '%s' 'Succeeded'
    ;;
  application:*'.status.sync.status}'*)
    printf '%s' 'Synced'
    ;;
  application:*'.spec.source.targetRevision}'*)
    printf '%s' "${sha}"
    ;;
  application:*'.status.sync.revision}'*)
    printf '%s' "${sha}"
    ;;
  application:*'git.targetRevision'*)
    printf '%s' "${sha}"
    ;;
  application:*'demoApi.localImage.enabled'*)
    printf '%s' 'true'
    ;;
  application:*'.spec.syncPolicy.automated}'*)
    exit 0
    ;;
  application:*'.spec.source.helm.parameters'*)
    if [ "${name}" = "demo-api" ]; then
      printf '%s\n' image.repository image.tag image.pullPolicy release.applicationVersion
    fi
    ;;
  rollout:*'helm\.sh/chart'*)
    printf '%s' 'demo-api-0.5.1'
    ;;
  analysistemplate:*'.provider.prometheus.address}'*)
    printf '%s' "${prometheus}"
    ;;
  *)
    exit 0
    ;;
esac
SH
chmod +x "${WORK_DIR}/feature-bin/git" "${WORK_DIR}/feature-bin/argocd" "${WORK_DIR}/feature-bin/kubectl"

echo "==> Exercising the unified feature workflow with fake Git and Argo CD clients"
(
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/feature-bin:${PATH}" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/feature-workflow-root.yaml" \
  TARGET_REVISION=feature/test \
  IMAGE_TAG=v0.11.3-local \
  EXPECTED_CHART_VERSION=0.5.1 \
  WAIT_TIMEOUT_SECONDS=5 \
  APPLICATION_IDLE_OBSERVATIONS=1 \
  OPERATION_RETRY_DELAY_SECONDS=0 \
    ./scripts/deploy-local-feature-gitops.sh
) >"${WORK_DIR}/feature-workflow.out" 2>"${WORK_DIR}/feature-workflow.err"
grep -q 'Local feature GitOps configuration passed.' "${WORK_DIR}/feature-workflow.out"
grep -q 'Commit:    0123456789abcdef0123456789abcdef01234567' "${WORK_DIR}/feature-workflow.out"
grep -q 'Root sync: Synced' "${WORK_DIR}/feature-workflow.out"

if command -v helm >/dev/null 2>&1; then
  echo "==> Linting and rendering stable/feature local platform Chart"
  helm lint "${ROOT_DIR}/clusters/local/platform" >/dev/null
  helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
    >"${WORK_DIR}/stable-platform.yaml"
  helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
    --set-string "git.targetRevision=${FEATURE_SHA}" \
    --set demoApi.localImage.enabled=true \
    --set-string demoApi.localImage.repository=startup-devops-baseline/demo-api \
    --set-string demoApi.localImage.tag=v0.11.3-local \
    --set-string demoApi.localImage.pullPolicy=Never \
    --set-string demoApi.localImage.applicationVersion=v0.11.3-local \
    >"${WORK_DIR}/feature-platform.yaml"

  python3 - \
    "${WORK_DIR}/stable-platform.yaml" \
    "${WORK_DIR}/feature-platform.yaml" \
    "${FEATURE_SHA}" \
    "${ROOT_DIR}/delivery/contracts/v0.11.4.0-grafana-recording-rules.json" \
    "${ROOT_DIR}/delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json" <<'PY'
from pathlib import Path
import re
import sys


stable = Path(sys.argv[1]).read_text()
feature = Path(sys.argv[2]).read_text()
sha = sys.argv[3]
observability_successor = Path(sys.argv[4]).is_file()
controller_metrics_successor = Path(sys.argv[5]).is_file()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def applications(text: str) -> dict[str, str]:
    result = {}
    for document in re.split(r"^---\s*$", text, flags=re.MULTILINE):
        if "kind: Application" not in document:
            continue
        name = re.search(r"^  name:\s*([^\s]+)", document, re.MULTILINE)
        require(name is not None, "Rendered Application name missing")
        result[name.group(1)] = document
    return result


stable_apps = applications(stable)
feature_apps = applications(feature)
expected_names = {"argo-rollouts", "ingress-nginx", "monitoring", "namespace-guardrails", "demo-api"}
same_repository_names = ["namespace-guardrails", "demo-api"]
if observability_successor:
    expected_names.add("observability-views")
    same_repository_names.append("observability-views")
require(set(stable_apps) == expected_names, "Stable child Application set changed")
require(set(feature_apps) == expected_names, "Feature child Application set changed")


def revision(document: str) -> str:
    match = re.search(r"^    targetRevision:\s*[\"']?([^\"'\s]+)", document, re.MULTILINE)
    require(match is not None, "Rendered targetRevision missing")
    return match.group(1)


for name in same_repository_names:
    require(revision(stable_apps[name]) == "HEAD", f"Stable {name} revision changed")
    require(revision(feature_apps[name]) == sha, f"Feature {name} revision is not unified")

expected_rollouts_version = "2.41.1" if controller_metrics_successor else "2.41.0"
require(revision(feature_apps["argo-rollouts"]) == expected_rollouts_version, "Argo Rollouts version changed")
require(revision(feature_apps["ingress-nginx"]) == "4.11.3", "ingress-nginx version changed")
require(revision(feature_apps["monitoring"]) == "88.5.0", "monitoring version changed")

require("parameters: []" in stable_apps["demo-api"], "Stable demo-api parameters are not explicit empty")
parameter_names = re.findall(r"^        - name:\s*(\S+)", feature_apps["demo-api"], re.MULTILINE)
require(
    parameter_names == ["image.repository", "image.tag", "image.pullPolicy", "release.applicationVersion"],
    "Feature demo-api parameter allowlist changed",
)

print("v0.11.3.4 Helm stable/feature render validation passed.")
PY
else
  echo "Helm unavailable; static and dynamic Root/revision validation passed. Helm render remains required in CI."
fi

echo "v0.11.3.4 unified feature revision rendering validation passed."
