#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_ENVIRONMENT="${EXPECTED_ENVIRONMENT:-}"
EXPECTED_EVIDENCE_ID="${EXPECTED_EVIDENCE_ID:-}"
EVIDENCE_FILE="${EVIDENCE_FILE:-${ROOT_DIR}/evidence/demo-api/runtime/${EXPECTED_ENVIRONMENT}/${EXPECTED_EVIDENCE_ID}.json}"
RELEASE_FILE="${RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${EXPECTED_ENVIRONMENT}.yaml}"
MAX_EVIDENCE_AGE_SECONDS="${MAX_EVIDENCE_AGE_SECONDS:-259200}"

python3 - "${EVIDENCE_FILE}" "${RELEASE_FILE}" "${EXPECTED_ENVIRONMENT}" \
  "${EXPECTED_EVIDENCE_ID}" "${MAX_EVIDENCE_AGE_SECONDS}" "${GITHUB_OUTPUT:-}" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys

evidence_name, release_name, environment, evidence_id, max_age_raw, github_output = sys.argv[1:]
evidence_path = Path(evidence_name)
release_path = Path(release_name)
if environment not in {"aws-dev", "aws-test", "aws-prod"}:
    raise SystemExit("Unsupported runtime evidence environment.")
if not re.fullmatch(r"[0-9]{14}", evidence_id):
    raise SystemExit("Runtime evidence ID must use UTC YYYYMMDDHHMMSS digits.")
try:
    max_age = int(max_age_raw)
except ValueError as error:
    raise SystemExit("MAX_EVIDENCE_AGE_SECONDS must be an integer.") from error
if max_age < 1:
    raise SystemExit("MAX_EVIDENCE_AGE_SECONDS must be positive.")
if not evidence_path.is_file() or not release_path.is_file():
    raise SystemExit("Runtime evidence or release file is missing.")


def scalar(raw):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def release_values(path):
    values = {}
    section = None
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
        elif indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            values[(section, key)] = scalar(value)
        else:
            raise SystemExit(f"{path}:{number}: unsupported release values structure")
    return values


document = json.loads(evidence_path.read_text())
if set(document) != {"schemaVersion", "application", "environment", "status", "release", "runtime"}:
    raise SystemExit("Runtime evidence top-level schema is not exact.")
if document["schemaVersion"] != "v0.9.5" or document["application"] != "demo-api" or document["status"] != "passed":
    raise SystemExit("Runtime evidence is not a passing v0.9.5 demo-api record.")
if document["environment"] != environment:
    raise SystemExit("Runtime evidence environment does not match the requested source.")

release = document["release"]
runtime = document["runtime"]
release_keys = {
    "path", "sha256", "imageRepository", "imageTag", "imageDigest",
    "applicationVersion", "sourceRepository", "sourceCommit", "buildWorkflowRunId",
}
runtime_keys = {
    "mode", "evidenceId", "actor", "recordedAt", "repositoryRevision",
    "clusterName", "argoApplication", "argoRevision", "namespace",
    "workloadKind", "workloadName", "rolloutPhase", "analysisRunName",
    "analysisRunPhase", "ingressHostname", "albActionSha256",
    "observedImage", "readyPodCount", "checks",
}
if set(release) != release_keys or set(runtime) != runtime_keys:
    raise SystemExit("Runtime evidence nested schema is not exact.")
if release["path"] != f"apps/demo-api/helm/values/releases/{environment}.yaml":
    raise SystemExit("Runtime evidence release path is inconsistent.")
if release["sha256"] != hashlib.sha256(release_path.read_bytes()).hexdigest():
    raise SystemExit("Runtime evidence is stale for the current source release.")

values = release_values(release_path)
expected_release = {
    "imageRepository": values[("image", "repository")],
    "imageTag": values[("image", "tag")],
    "imageDigest": values[("image", "digest")],
    "applicationVersion": values[("release", "applicationVersion")],
    "sourceRepository": values[("delivery", "sourceRepository")],
    "sourceCommit": values[("delivery", "sourceCommit")],
    "buildWorkflowRunId": values[("delivery", "workflowRunId")],
}
if {key: release[key] for key in expected_release} != expected_release:
    raise SystemExit("Runtime evidence release identity differs from the current release.")
if runtime["mode"] != "aws-runtime-verification" or runtime["evidenceId"] != evidence_id:
    raise SystemExit("Runtime evidence identity or mode is invalid.")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", runtime["actor"]):
    raise SystemExit("Runtime evidence actor is invalid.")
if runtime["repositoryRevision"] != runtime["argoRevision"] or not re.fullmatch(r"[0-9a-f]{40}", runtime["repositoryRevision"]):
    raise SystemExit("Runtime evidence does not bind Argo CD to a full Git revision.")
if runtime["observedImage"] != f'{release["imageRepository"]}@{release["imageDigest"]}':
    raise SystemExit("Runtime evidence Pod image differs from the release digest.")
if not isinstance(runtime["readyPodCount"], int) or runtime["readyPodCount"] < 1:
    raise SystemExit("Runtime evidence requires at least one ready Pod.")

expected_resources = {
    "aws-dev": ("startup-devops-baseline-dev", "demo-api-aws-dev", "Deployment", "demo.dev.aureumstack.com"),
    "aws-test": ("startup-devops-baseline-test", "demo-api-aws-test", "Rollout", "demo.test.aureumstack.com"),
    "aws-prod": ("startup-devops-baseline-prod", "demo-api-aws-prod", "Rollout", "demo.prod.aureumstack.com"),
}[environment]
observed_resources = (
    runtime["clusterName"], runtime["argoApplication"], runtime["workloadKind"],
    runtime["ingressHostname"],
)
if observed_resources != expected_resources or runtime["namespace"] != "startup-apps" or runtime["workloadName"] != "demo-api":
    raise SystemExit("Runtime evidence resource identity differs from the environment contract.")

base_checks = {
    "argocd-synced-healthy", "release-annotations-match", "all-pods-ready",
    "immutable-pod-image-match", "https-health", "https-ready-database",
    "https-version-identity",
}
if environment == "aws-dev":
    if runtime["rolloutPhase"] != "not-applicable" or runtime["analysisRunName"] or runtime["analysisRunPhase"] != "not-applicable" or runtime["albActionSha256"]:
        raise SystemExit("aws-dev runtime evidence must describe the Deployment baseline.")
    expected_checks = base_checks
else:
    if runtime["rolloutPhase"] != "Healthy" or runtime["analysisRunPhase"] != "Successful" or not runtime["analysisRunName"]:
        raise SystemExit("Runtime evidence does not prove a successful progressive rollout.")
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", runtime["analysisRunName"]):
        raise SystemExit("Runtime evidence AnalysisRun name is invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", runtime["albActionSha256"]):
        raise SystemExit("Runtime evidence does not bind the completed ALB action.")
    expected_checks = base_checks | {
        "rollout-healthy", "analysis-run-successful",
        "analysis-release-identity-match", "alb-stable-weight-100",
    }
if set(runtime["checks"]) != expected_checks or len(runtime["checks"]) != len(expected_checks):
    raise SystemExit("Runtime evidence checks are incomplete or duplicated.")

try:
    recorded_at = datetime.strptime(runtime["recordedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
except (TypeError, ValueError) as error:
    raise SystemExit("Runtime evidence timestamp is invalid.") from error
age = (datetime.now(timezone.utc) - recorded_at).total_seconds()
if age < -300:
    raise SystemExit("Runtime evidence timestamp is unexpectedly in the future.")
if age > max_age:
    raise SystemExit("Runtime evidence has expired; validate the source runtime again.")

digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
if github_output:
    with Path(github_output).open("a") as output:
        output.write(f"runtime-evidence-sha256={digest}\n")
        output.write(f"runtime-evidence-recorded-at={runtime['recordedAt']}\n")
print(f"demo-api AWS runtime evidence passed: {environment} {evidence_id} {digest}")
PY
