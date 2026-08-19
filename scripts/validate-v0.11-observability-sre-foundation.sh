#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11-observability-sre-foundation.json"
DESIGN="${ROOT_DIR}/docs/V0.11_OBSERVABILITY_SRE_DESIGN.md"
ROADMAP="${ROOT_DIR}/docs/ROADMAP.md"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Validating v0.11.0 machine-readable design boundary"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.11-observability-sre-foundation.json"
design_path = root / "docs/V0.11_OBSERVABILITY_SRE_DESIGN.md"
roadmap_path = root / "docs/ROADMAP.md"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing file: {path.relative_to(root)}")
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"Invalid JSON in {path.relative_to(root)}: {exc}"
        ) from exc
    require(isinstance(value, dict), f"Expected object: {path.relative_to(root)}")
    return value


EXPECTED_INCREMENTS = [f"v0.11.{index}" for index in range(9)]
EXPECTED_INCREMENT_NAMES = [
    "observability-sre-design-foundation",
    "production-metrics-foundation",
    "application-and-platform-telemetry",
    "dashboards-and-recording-rules",
    "actionable-alerting-and-runbooks",
    "centralized-logging-and-extensible-tracing",
    "sli-slo-and-progressive-delivery-gates",
    "multi-environment-observability-qualification",
    "clean-room-end-to-end-acceptance",
]
EXPECTED_ENVIRONMENTS = ["local", "aws-dev", "aws-test", "aws-prod"]
EXPECTED_ATTRIBUTES = [
    "service.name",
    "service.version",
    "deployment.environment.name",
    "platform.release.id",
    "platform.source.commit",
    "container.image.digest",
]
EXPECTED_DEFERRED = [
    "remote-terraform-state-and-locking",
    "state-backup-and-recovery",
    "platform-upgrade-lifecycle",
    "clean-room-infrastructure-rebuild-capstone",
    "measured-rto-rpo",
    "break-glass-and-production-access-review",
    "repository-wide-production-readiness-acceptance",
]


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.11.0", "Bad schemaVersion")
    require(contract.get("version") == "v0.11", "Bad version")
    require(contract.get("status") == "design-foundation", "Bad status")
    require(
        contract.get("repository") == "SterlingAureum/startup-devops-baseline",
        "Unexpected repository",
    )

    if check_files:
        for field in ("designDocument", "roadmapDocument"):
            path = contract.get(field)
            require(isinstance(path, str) and (root / path).is_file(), f"Missing {field}")

    previous = contract.get("previousVersionBoundary")
    require(isinstance(previous, dict), "Missing previousVersionBoundary")
    require(previous.get("version") == "v0.10", "v0.10 boundary changed")
    require(previous.get("acceptanceEvidenceImmutable") is True, "v0.10 evidence is mutable")
    require(previous.get("contractsRemainAuthoritativeForV010") is True, "v0.10 contracts displaced")
    require(previous.get("orchestratorBehaviorChangedByV0110") is False, "v0.11.0 changes orchestration")
    require(previous.get("workflowPermissionsChangedByV0110") is False, "v0.11.0 changes workflow permissions")

    increments = contract.get("increments")
    require(isinstance(increments, list), "increments must be an array")
    require([item.get("id") for item in increments] == EXPECTED_INCREMENTS, "Increment order changed")
    require([item.get("name") for item in increments] == EXPECTED_INCREMENT_NAMES, "Increment names changed")
    require(increments[0].get("status") == "delivered", "v0.11.0 is not delivered")
    require(all(item.get("status") == "planned" for item in increments[1:]), "Future increment claims delivery")

    signals = contract.get("signals")
    require(isinstance(signals, dict), "Missing signals")
    require(signals.get("required") == ["metrics", "logs", "traces"], "Signal set changed")
    traces = signals.get("traces")
    require(isinstance(traces, dict), "Missing trace contract")
    require(traces.get("scope") == "minimal-extensible-foundation", "Trace scope changed")
    require(traces.get("protocol") == "otlp", "Trace protocol must be OTLP")
    require(traces.get("propagation") == "w3c-trace-context", "Trace propagation changed")
    require(traces.get("applicationBackendCoupling") is False, "Application is coupled to a trace backend")
    require(traces.get("initialPath") == "http-to-demo-api-to-postgresql", "Initial trace path changed")
    require(traces.get("samplingConfiguredOutsideApplicationCode") is True, "Sampling is hard-coded")
    require(traces.get("fullDistributedTracingPlatformRequired") is False, "v0.11.0 requires a complex trace platform")

    attributes = contract.get("resourceAttributes")
    require(isinstance(attributes, dict), "Missing resource attributes")
    require(attributes.get("required") == EXPECTED_ATTRIBUTES, "Stable resource attributes changed")
    forbidden_dimensions = attributes.get("forbiddenHighCardinalityDimensions")
    require(isinstance(forbidden_dimensions, list) and len(forbidden_dimensions) >= 5, "Cardinality guard is incomplete")

    profiles = contract.get("environmentProfiles")
    require(isinstance(profiles, list), "Missing environment profiles")
    require([item.get("environment") for item in profiles] == EXPECTED_ENVIRONMENTS, "Environment profile order changed")
    require(profiles[-1].get("profile") == "production-parity", "aws-prod profile weakened")
    require(profiles[-1].get("productionClaim") == "requires-live-v0.11-acceptance", "aws-prod live evidence requirement missing")
    require(all(item.get("productionClaim") is False for item in profiles[:-1]), "Non-production profile claims production")

    sre = contract.get("sreModel")
    require(isinstance(sre, dict), "Missing SRE model")
    require(sre.get("goldenSignals") == ["latency", "traffic", "errors", "saturation"], "Golden signals changed")
    require(sre.get("serviceLevelObjectives") == "defined-from-measured-baseline", "SLOs are not measurement-based")
    require(sre.get("errorBudgetRequired") is True, "Error budget missing")
    require(sre.get("burnRateAlertingRequired") is True, "Burn-rate alerting missing")
    require(sre.get("alertsRequireRunbooks") is True, "Runbook requirement missing")

    security = contract.get("securityAndCost")
    require(isinstance(security, dict), "Missing security and cost boundary")
    for key in (
        "credentialsInTelemetry",
        "requestBodiesInTelemetryByDefault",
        "authorizationHeadersInTelemetry",
        "rawSqlParametersInTelemetry",
        "publicObservabilityEndpoints",
    ):
        require(security.get(key) is False, f"Unsafe telemetry boundary enabled: {key}")
    for key in (
        "boundedLabelCardinality",
        "explicitRetentionRequired",
        "environmentSpecificSizingRequired",
        "networkPolicyRequired",
    ):
        require(security.get(key) is True, f"Required control disabled: {key}")

    automation = contract.get("automationBoundary")
    require(isinstance(automation, dict), "Missing automation boundary")
    for key in (
        "automaticEnvironmentCreation",
        "automaticPullRequestMerge",
        "automaticProductionRolloutProgression",
        "automaticRollback",
        "productionKubernetesWriteByQualification",
        "productionAwsMutationByQualification",
    ):
        require(automation.get(key) is False, f"Unsafe automation enabled: {key}")
    for key in (
        "productionEnvironmentApprovalRequired",
        "productionPullRequestReviewRequired",
        "humanRecoveryDecisionRequired",
    ):
        require(automation.get(key) is True, f"Human control disabled: {key}")
    require(
        automation.get("productionRuntimeObservation") == "approval-protected-read-only",
        "Production runtime observation is not approval-protected and read-only",
    )

    acceptance = contract.get("finalAcceptance")
    require(isinstance(acceptance, dict), "Missing final acceptance")
    require(acceptance.get("increment") == "v0.11.8", "Final acceptance increment changed")
    require(acceptance.get("mode") == "clean-room-dev-test-prod-live-observability", "Acceptance mode changed")
    require(acceptance.get("candidate") == "post-v0.10.8.7-security-hotfix-image", "Acceptance candidate changed")
    require(acceptance.get("liveEnvironments") == ["aws-dev", "aws-test", "aws-prod"], "Live environment order changed")
    require(acceptance.get("buildOnce") is True, "Acceptance does not build once")
    require(acceptance.get("sameDigestAcrossEnvironments") is True, "Digest identity not preserved")
    require(acceptance.get("automaticClusterCreation") is False, "Acceptance auto-creates clusters")
    require(acceptance.get("automaticMerge") is False, "Acceptance auto-merges")
    require(acceptance.get("automaticRollback") is False, "Acceptance auto-rolls back")
    checkpoints = acceptance.get("requiredCheckpoints")
    require(isinstance(checkpoints, list), "Missing acceptance checkpoints")
    for checkpoint in (
        "successful-end-to-end-release",
        "intentionally-failed-canary-analysis",
        "actionable-alert-observed",
        "metric-log-trace-release-correlation",
        "aws-prod-read-only-observability-qualification",
        "reviewed-final-evidence",
        "disposable-environment-teardown",
        "residual-cost-audit",
    ):
        require(checkpoint in checkpoints, f"Missing checkpoint: {checkpoint}")

    require(contract.get("deferredToV012") == EXPECTED_DEFERRED, "v0.12 boundary changed")

    repository = contract.get("repositoryBoundary")
    require(isinstance(repository, dict), "Missing repository boundary")
    require(repository.get("aiInfrastructureRepository") == "SterlingAureum/ai-infra-blueprints", "AI infrastructure repository changed")
    require(repository.get("openClawIntegration") is False, "OpenClaw entered v0.11 scope")
    require(repository.get("aiopsImplementationInV011") is False, "AIOps entered v0.11 scope")
    ai_scope = repository.get("deferredToAiInfrastructureRepository")
    require(isinstance(ai_scope, list), "Missing AI infrastructure deferrals")
    for capability in (
        "gpu-node-pools",
        "nvidia-drivers-and-operators",
        "vllm-model-serving",
        "model-artifact-lifecycle",
        "gpu-and-inference-benchmarking",
        "slurm-training-infrastructure",
    ):
        require(capability in ai_scope, f"AI infrastructure ownership drift: {capability}")


contract = load_json(contract_path)
validate_contract(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("mutable v0.10 evidence", lambda value: value["previousVersionBoundary"].__setitem__("acceptanceEvidenceImmutable", False)),
    ("backend-coupled tracing", lambda value: value["signals"]["traces"].__setitem__("applicationBackendCoupling", True)),
    ("hard-coded sampling", lambda value: value["signals"]["traces"].__setitem__("samplingConfiguredOutsideApplicationCode", False)),
    ("automatic environment creation", lambda value: value["automationBoundary"].__setitem__("automaticEnvironmentCreation", True)),
    ("automatic production merge", lambda value: value["automationBoundary"].__setitem__("automaticPullRequestMerge", True)),
    ("automatic rollback", lambda value: value["automationBoundary"].__setitem__("automaticRollback", True)),
    ("production Kubernetes write", lambda value: value["automationBoundary"].__setitem__("productionKubernetesWriteByQualification", True)),
    ("missing production approval", lambda value: value["automationBoundary"].__setitem__("productionEnvironmentApprovalRequired", False)),
    ("public monitoring endpoint", lambda value: value["securityAndCost"].__setitem__("publicObservabilityEndpoints", True)),
    ("credentials in telemetry", lambda value: value["securityAndCost"].__setitem__("credentialsInTelemetry", True)),
    ("automatic acceptance rollback", lambda value: value["finalAcceptance"].__setitem__("automaticRollback", True)),
    ("AIOps in v0.11", lambda value: value["repositoryBoundary"].__setitem__("aiopsImplementationInV011", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise SystemExit(f"Unsafe v0.11.0 mutation was accepted: {label}")

roadmap = roadmap_path.read_text()
for marker in (
    "## v0.11 - Observability and SRE Baseline",
    "Status: In Progress",
    "## v0.12 - Production Readiness Capstone",
    "## v1.0 - Production-ready Commercial Baseline",
    "## v1.1 - AI Infrastructure Integration",
    "## v1.2 - Lightweight AIOps Extension",
):
    require(marker in roadmap, f"Roadmap marker missing: {marker}")
require(
    roadmap.index("## v0.11 - Observability and SRE Baseline")
    < roadmap.index("## v0.12 - Production Readiness Capstone")
    < roadmap.index("## v1.0 - Production-ready Commercial Baseline")
    < roadmap.index("## v1.1 - AI Infrastructure Integration")
    < roadmap.index("## v1.2 - Lightweight AIOps Extension"),
    "Roadmap version order is invalid",
)

design = design_path.read_text()
for marker in (
    "## Extensible Tracing Foundation",
    "HTTP request -> demo-api server span -> PostgreSQL client span",
    "## SLI and SLO Model",
    "## Delivery Integration Boundary",
    "## Final Acceptance Direction",
    "## Deferred to v0.12",
    "## Repository Boundary",
):
    require(marker in design, f"Design marker missing: {marker}")

readme = (root / "README.md").read_text()
require(
    re.search(r"v0\.11\.[1-8][a-z0-9.-]*", readme) is not None,
    "README current version did not advance beyond the v0.11.0 design checkpoint",
)
require("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md" in readme, "README does not link the design")

observability = (root / "docs/OBSERVABILITY.md").read_text()
require("## Detailed v0.11 Contracts" in observability, "Observability guide is not linked to v0.11")
require("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md" in observability, "Observability guide does not link the design")

active_documents = [
    root / "docs/AWS_MULTI_ENVIRONMENT_LIFECYCLE.md",
    root / "docs/MULTI_ENVIRONMENT_GITOPS_MODEL.md",
    root / "docs/AWS_PROGRESSIVE_DELIVERY.md",
]
stale_pattern = re.compile(r"v1\.0[^\n]{0,80}observability|observability[^\n]{0,80}v1\.0", re.IGNORECASE)
for path in active_documents:
    require(not stale_pattern.search(path.read_text()), f"Stale v1.0 observability reference: {path.relative_to(root)}")

evidence_files = sorted((root / "evidence/v0.10/final").glob("*.json"))
require(evidence_files, "Accepted v0.10 evidence is missing")
for path in evidence_files:
    evidence = load_json(path)
    require(evidence.get("version") == "v0.10", f"Unexpected evidence version: {path.name}")
    require(evidence.get("status") == "accepted", f"v0.10 evidence is not accepted: {path.name}")

print("v0.11 Observability and SRE design foundation contracts passed.")
PY
