#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])


def require(path, fragments, description):
    text = path.read_text()
    for fragment in fragments:
        if fragment not in text:
            raise SystemExit(f"{path.relative_to(root)}: {description} is missing: {fragment}")
    return text


def top_level_section(text, name):
    match = re.search(rf"(?m)^{re.escape(name)}:\s*$", text)
    if not match:
        raise SystemExit(f"Missing top-level values section: {name}")
    end = re.search(r"(?m)^[A-Za-z][A-Za-z0-9]*:\s*$", text[match.end():])
    return text[match.start(): match.end() + end.start()] if end else text[match.start():]


values_dir = root / "apps/demo-api/helm/values/environments"
dev_text = (values_dir / "aws-dev.yaml").read_text()
if "enabled: false" not in top_level_section(dev_text, "rollout") or \
        "enabled: false" not in top_level_section(dev_text, "analysis"):
    raise SystemExit("aws-dev must retain its validated Deployment baseline in v0.9.5.")

expected_steps = {
    "aws-test": """      steps:
        - setWeight: 20
        - pause:
            duration: 60s
        - analysis:
            templates:
              - templateName: demo-api-canary-health
        - setWeight: 50
        - pause: {}
        - setWeight: 100""",
    "aws-prod": """      steps:
        - setWeight: 10
        - pause:
            duration: 5m
        - analysis:
            templates:
              - templateName: demo-api-canary-health
        - setWeight: 25
        - pause: {}
        - setWeight: 50
        - pause:
            duration: 10m
        - setWeight: 100""",
}
for environment in ("aws-test", "aws-prod"):
    path = values_dir / f"{environment}.yaml"
    text = path.read_text()
    rollout = top_level_section(text, "rollout")
    analysis = top_level_section(text, "analysis")
    for fragment in (
        "  enabled: true", "      maxSurge: 1", "      maxUnavailable: 0",
        "      stableService: demo-api-stable", "      canaryService: demo-api-canary",
        "        nginx:\n          enabled: false",
        "        alb:\n          enabled: true\n          ingress: demo-api\n          servicePort: 80",
        expected_steps[environment],
    ):
        if fragment not in rollout:
            raise SystemExit(f"{environment} Rollout contract is missing: {fragment}")
    if "  enabled: true" not in analysis or "  provider: web" not in analysis:
        raise SystemExit(f"{environment} must enable the Web AnalysisRun provider.")

rollout_template = require(
    root / "apps/demo-api/helm/templates/rollout.yaml",
    (
        "trafficRouting.alb.enabled", "servicePort:",
        "metadata.annotations['platform.startup.dev/image-digest']",
        "metadata.annotations['platform.startup.dev/source-commit']",
    ),
    "ALB Rollout identity binding",
)
require(
    root / "apps/demo-api/helm/templates/ingress.yaml",
    ("$albRoutingEnabled", "name: use-annotation"),
    "ALB action backend",
)
require(
    root / "apps/demo-api/helm/templates/service.yaml",
    ("$albRoutingEnabled", "or $nginxRoutingEnabled $albRoutingEnabled"),
    "stable/canary Service routing",
)
require(
    root / "apps/demo-api/helm/templates/analysis-template.yaml",
    (
        "provider:", "web:", "canary-ready", "canary-release-identity",
        '{{ args.expected-environment }}', '{{ args.expected-version }}',
    ),
    "Web AnalysisRun contract",
)

require(
    root / "clusters/aws/base/platform/argo-rollouts.yaml",
    (
        "name: argo-rollouts", "repoURL: https://argoproj.github.io/argo-helm",
        "chart: argo-rollouts", "targetRevision: 2.41.0",
        'argocd.argoproj.io/sync-wave: "-15"', "ServerSideApply=true",
    ),
    "pinned AWS Argo Rollouts Application",
)
require(
    root / "clusters/aws/base/platform/kustomization.yaml",
    ("  - argo-rollouts.yaml",),
    "AWS platform resource",
)
require(
    root / "clusters/aws/base/platform/demo-api.yaml",
    (
        "name: demo-api-stable", "name: demo-api-canary", "- /spec/selector",
        '.metadata.annotations."alb.ingress.kubernetes.io/actions.demo-api-stable"',
        '.metadata.annotations."rollouts.argoproj.io/managed-alb-actions"',
        "RespectIgnoreDifferences=true",
    ),
    "Argo CD Rollout field ownership",
)
require(
    root / "clusters/aws/base/security/network-policies/startup-apps/policies.yaml",
    (
        "name: allow-argo-rollouts-analysis-to-demo-api",
        "kubernetes.io/metadata.name: argo-rollouts",
        "app.kubernetes.io/name: argo-rollouts",
        "port: 8080",
    ),
    "least-privilege AnalysisRun ingress",
)

promotion = require(
    root / ".github/workflows/demo-api-promote-environment.yaml",
    (
        "runtime_evidence_id:",
        "evidence/demo-api/runtime/${SOURCE_ENVIRONMENT}/${RUNTIME_EVIDENCE_ID}.json",
        "./scripts/validate-demo-api-runtime-evidence.sh",
    ),
    "runtime evidence Promotion gate",
)
if re.search(r"(?im)\b(aws\s+eks|update-kubeconfig|kubectl)\b", promotion):
    raise SystemExit("Promotion workflow must remain isolated from EKS.")

print("demo-api AWS progressive-delivery declaration passed.")
PY
