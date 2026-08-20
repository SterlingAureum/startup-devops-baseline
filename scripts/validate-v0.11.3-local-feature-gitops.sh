#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

echo "==> Validating v0.11.3 local feature GitOps workflow"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
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


def load_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads(read(relative))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {relative}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def require_markers(relative: str, markers: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in markers:
        require(marker in text, f"{relative}: missing marker {marker!r}")
    return text


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.11.3", "Bad schemaVersion")
    require(contract.get("version") == "v0.11.3", "Bad version")
    require(contract.get("status") == "offline-implemented", "Bad status")
    require(contract.get("liveAcceptanceClaimed") is False, "Live acceptance is claimed")

    if check_files:
        require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
        for path in contract.get("scripts", {}).values():
            require(isinstance(path, str) and (root / path).is_file(), f"Missing script: {path}")

    stable = contract.get("stableDeclaration")
    require(isinstance(stable, dict), "Missing stableDeclaration")
    require(stable.get("rootRevision") == "HEAD", "Stable root is not HEAD")
    require(stable.get("sameRepositoryChildRevision") == "HEAD", "Stable child is not HEAD")
    require(stable.get("featureRevisionCommittedToActiveManifests") is False, "Feature revision is committed")
    require(stable.get("activeRevisionValidatorPreserved") is True, "Active revision validator removed")

    feature = contract.get("featureValidation")
    require(isinstance(feature, dict), "Missing featureValidation")
    require(feature.get("revisionInput") == "TARGET_REVISION", "Feature revision input changed")
    require(feature.get("revisionInputRequired") is True, "Feature revision input became optional")
    require(feature.get("rootSyncMode") == "manual", "Feature root is not manual")
    require(feature.get("rootManifestAppliedManualBeforeCreation") is True, "Root manifest can auto-sync before manual mode")
    require(feature.get("rootSyncedBeforeChildOverrides") is True, "Unsafe sync ordering")
    require(feature.get("applicationOperationsSerialized") is True, "Application operations are not serialized")
    require(feature.get("childAutomationPausedDuringOverrides") is True, "Child automation is not paused")
    require(
        feature.get("sameRepositoryApplications")
        == ["startup-devops-root", "namespace-guardrails", "demo-api"],
        "Same-repository Application set changed",
    )
    require(feature.get("prometheusAddressOverridden") is False, "Source telemetry configuration is masked")
    require(feature.get("helmParameterAllowlistEnforced") is True, "Helm parameter allowlist is not enforced")
    require(feature.get("expectedRootSyncStatusAfterChildOverrides") == "OutOfSync", "Root drift semantics changed")
    require(feature.get("rootResyncDuringValidationAllowed") is False, "Root resync is allowed")

    runtime = contract.get("runtimeAssertions")
    require(isinstance(runtime, dict), "Missing runtimeAssertions")
    for key in (
        "applicationTargetRevision",
        "rootAutomationDisabled",
        "chartVersionMatchesLocalCheckout",
        "serviceMonitorExists",
        "prometheusAddressMatchesExpected",
    ):
        require(runtime.get(key) is True, f"Runtime assertion disabled: {key}")
    require(runtime.get("rolloutAutoPromoted") is False, "Canary is auto-promoted")
    require(runtime.get("rolloutFullPromotionAllowed") is False, "Full promotion is allowed")

    restoration = contract.get("restoration")
    require(isinstance(restoration, dict), "Missing restoration")
    require(restoration.get("rootRevision") == "HEAD", "Restoration does not use HEAD")
    require(restoration.get("rootSyncModeDuringCleanup") == "manual", "Restoration cleanup is not deterministic")
    require(restoration.get("rootSyncModeAfterCleanup") == "automated", "Restoration does not restore automation")
    require(restoration.get("liveHelmParametersRemovedExplicitly") is True, "Live Helm parameters are not explicitly removed")
    require(restoration.get("emptyHelmParameterSetAsserted") is True, "Empty Helm parameter state is not asserted")
    require(restoration.get("rootSelfHealRestored") is True, "Root self-heal not restored")

    boundary = contract.get("automationBoundary")
    require(isinstance(boundary, dict), "Missing automationBoundary")
    for key in (
        "trackedManifestMutation",
        "hardcodedFeatureRevision",
        "awsMutation",
        "releaseOrchestratorChanged",
        "imagePublishWorkflowChanged",
        "promotionWorkflowChanged",
        "rollbackWorkflowChanged",
        "automaticCanaryPromotion",
        "automaticProductionWrite",
    ):
        require(boundary.get(key) is False, f"Automation boundary expanded: {key}")

    acceptance = contract.get("acceptance")
    require(isinstance(acceptance, dict), "Missing acceptance")
    require(acceptance.get("offlineValidationRequired") is True, "Offline validation is optional")
    require(acceptance.get("localFeatureLiveValidationRequiredBeforeTag") is True, "Live feature validation is optional")
    require(acceptance.get("headRestorationRequiredAfterFeatureValidation") is True, "HEAD restoration is optional")
    require(acceptance.get("awsValidationRequired") is False, "Local workflow incorrectly requires AWS")

    roadmap = contract.get("roadmapShift")
    require(isinstance(roadmap, dict), "Missing roadmapShift")
    require(roadmap.get("dashboardsAndRecordingRules") == "v0.11.4", "Dashboard increment changed")
    require(roadmap.get("finalAcceptance") == "v0.11.9", "Final acceptance increment changed")


def validate_repository() -> None:
    root_deploy = require_markers(
        "scripts/deploy-root-app.sh",
        (
            'TARGET_REVISION="${TARGET_REVISION:-HEAD}"',
            'ROOT_SYNC_MODE="${ROOT_SYNC_MODE:-}"',
            'ROOT_SYNC_MODE="manual"',
            'ROOT_SYNC_MODE="automated"',
            'repoURL: .*\\$#    repoURL:',
            'targetRevision: .*\\$#    targetRevision:',
            'targetRevision: ${TARGET_REVISION}',
            "automated\":null",
            "SYNC_MODE_FILE",
            "Applying Argo CD root application",
        ),
    )
    require("TARGET_REVISION:-main" not in root_deploy, "Local default changed from HEAD")

    feature = require_markers(
        "scripts/deploy-local-feature-gitops.sh",
        (
            'TARGET_REVISION="${TARGET_REVISION:-}"',
            "TARGET_REVISION is required for feature validation",
            "ROOT_SYNC_MODE=manual",
            'sync_application_if_needed "${ROOT_APP_NAME}"',
            'argocd app set "${GUARDRAILS_APP_NAME}" --revision "${TARGET_REVISION}"',
            'argocd app set "${DEMO_APP_NAME}"',
            "image.pullPolicy=Never",
            "resolved source commit",
            "remove_unexpected_demo_parameters",
            "demo-api local Helm parameter allowlist",
            "wait_for_application_idle",
            "--operation",
            "get servicemonitor",
            "provider.prometheus.address",
            "Do not sync ${ROOT_APP_NAME} again during feature validation.",
            "kubectl argo rollouts retry rollout",
        ),
    )
    require(
        feature.index('sync_application_if_needed "${ROOT_APP_NAME}"')
        < feature.index('argocd app set "${DEMO_APP_NAME}"'),
        "Root is not synced before child override",
    )
    for forbidden in (
        "feature/v0.11-observability-sre-baseline",
        "analysis.prometheus.address=",
        "kubectl argo rollouts promote",
        "--full",
        "sed -i",
        "git checkout",
    ):
        require(forbidden not in feature, f"Feature script contains forbidden behavior: {forbidden}")

    restore = require_markers(
        "scripts/restore-local-gitops-head.sh",
        (
            "TARGET_REVISION=HEAD",
            "ROOT_SYNC_MODE=manual",
            'sync_application_if_needed "${ROOT_APP_NAME}"',
            "remove_all_demo_parameters",
            'set_application_automation "${ROOT_APP_NAME}" automated',
            'assert_head_revision "${DEMO_APP_NAME}"',
            "root automated self-heal was not restored",
        ),
    )
    require("TARGET_REVISION=main" not in restore, "Local restoration changed to main")

    for relative in (
        "clusters/local/root-app.yaml",
        "clusters/local/platform/demo-api.yaml",
        "clusters/local/platform/namespace-guardrails.yaml",
    ):
        text = read(relative)
        require("targetRevision: HEAD" in text, f"{relative}: stable HEAD declaration changed")
        require(re.search(r"targetRevision:\s*feature/", text) is None, f"{relative}: feature branch committed")

    require_markers(
        "docs/V0.11.3_LOCAL_FEATURE_GITOPS_VALIDATION.md",
        (
            "Root Application becomes",
            "OutOfSync while remaining Healthy",
            "deploy-local-feature-gitops.sh",
            "restore-local-gitops-head.sh",
            "feature/v0.11-observability-sre-baseline",
            "Manual Canary Completion",
        ),
    )
    require_markers(
        "docs/LOCAL_DEPLOYMENT.md",
        (
            "Stable HEAD deployment",
            "Feature-revision validation",
            "deploy-local-feature-gitops.sh",
            "restore-local-gitops-head.sh",
        ),
    )
    require_markers(
        "docs/TROUBLESHOOTING.md",
        ("Root Is OutOfSync During Feature Validation", "Do not sync the Root Application"),
    )
    require_markers(
        ".github/CODEOWNERS",
        (
            "/delivery/contracts/v0.11.3-local-feature-gitops-validation.json @SterlingAureum",
            "/scripts/validate-v0.11.3-local-feature-gitops.sh @SterlingAureum",
            "/docs/V0.11.3_LOCAL_FEATURE_GITOPS_VALIDATION.md @SterlingAureum",
        ),
    )


contract = load_json("delivery/contracts/v0.11.3-local-feature-gitops-validation.json")
validate_contract(contract)
validate_repository()

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("live acceptance claim", lambda value: value.update(liveAcceptanceClaimed=True)),
    ("feature revision committed", lambda value: value["stableDeclaration"].update(featureRevisionCommittedToActiveManifests=True)),
    ("automatic feature root", lambda value: value["featureValidation"].update(rootSyncMode="automated")),
    ("unserialized Argo operations", lambda value: value["featureValidation"].update(applicationOperationsSerialized=False)),
    ("Helm allowlist disabled", lambda value: value["featureValidation"].update(helmParameterAllowlistEnforced=False)),
    ("root resync allowed", lambda value: value["featureValidation"].update(rootResyncDuringValidationAllowed=True)),
    ("Prometheus source masked", lambda value: value["featureValidation"].update(prometheusAddressOverridden=True)),
    ("automatic Canary promotion", lambda value: value["automationBoundary"].update(automaticCanaryPromotion=True)),
    ("HEAD restoration optional", lambda value: value["acceptance"].update(headRestorationRequiredAfterFeatureValidation=False)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case was accepted: {name}")

print("v0.11.3 local feature GitOps validation passed.")
PY
