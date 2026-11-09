#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
tf_root = root / "infra/terraform/aws/environments"
all_types = ("api", "audit", "authenticator", "controllerManager", "scheduler")
expected = {
    "dev": ((), "14"),
    "test": ((), "30"),
    "prod": (all_types, "90"),
}


def variable_block(text: str, name: str) -> str:
    marker = f'variable "{name}" {{'
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"Missing Terraform variable: {name}")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise SystemExit(f"Unterminated Terraform variable: {name}")


for environment, (expected_types, expected_retention) in expected.items():
    variables = (tf_root / environment / "variables.tf").read_text()
    log_block = variable_block(variables, "eks_enabled_cluster_log_types")
    default_match = re.search(r"default\s*=\s*\[(.*?)\]", log_block, re.DOTALL)
    if not default_match:
        raise SystemExit(f"{environment}: missing logging default")
    actual_types = tuple(re.findall(r'"([^"]+)"', default_match.group(1)))
    if actual_types != expected_types:
        raise SystemExit(
            f"{environment}: logging default {actual_types!r}, expected {expected_types!r}"
        )

    retention_block = variable_block(variables, "eks_cluster_log_retention_days")
    retention_match = re.search(r"(?m)^\s*default\s*=\s*(\d+)\s*$", retention_block)
    if not retention_match or retention_match.group(1) != expected_retention:
        raise SystemExit(f"{environment}: unexpected logging retention default")

prod_variables = (tf_root / "prod/variables.tf").read_text()
prod_log_block = variable_block(prod_variables, "eks_enabled_cluster_log_types")
if "toset(var.eks_enabled_cluster_log_types) == toset([" not in prod_log_block:
    raise SystemExit("prod: complete control-plane logging is not fail closed")

module_main = (root / "infra/terraform/aws/modules/eks/main.tf").read_text()
for marker in (
    "enabled_cluster_log_types = var.enabled_cluster_log_types",
    "retention_in_days = var.cluster_log_retention_days",
    "aws_cloudwatch_log_group.cluster",
):
    if marker not in module_main:
        raise SystemExit(f"EKS module is missing logging contract: {marker}")

context = (root / "scripts/aws-environment-context.sh").read_text()
for marker in (
    'EKS_CONTROL_PLANE_LOGGING_PROFILE="${EKS_CONTROL_PLANE_LOGGING_PROFILE:-off}"',
    'EKS_CONTROL_PLANE_LOGGING_PROFILE="${EKS_CONTROL_PLANE_LOGGING_PROFILE:-production-parity}"',
):
    if marker not in context:
        raise SystemExit(f"Environment logging profile is missing: {marker}")

profile_script = (root / "scripts/apply-eks-control-plane-logging-profile.sh").read_text()
for marker in (
    "apply-eks-logging-profile",
    "production-parity",
    'AWS_ENVIRONMENT}" == "aws-prod"',
    'LOG_TYPES_JSON=\'["api","audit","authenticator","controllerManager","scheduler"]\'',
    "eks_cluster_log_retention_days=",
):
    if marker not in profile_script:
        raise SystemExit(f"Guarded logging profile script is missing: {marker}")

cidr_script = (root / "scripts/apply-eks-api-access-cidr.sh").read_text()
for marker in (
    "REQUESTED_LOG_TYPES_JSON",
    "Preserving EKS control-plane log types",
    ".cluster.logging.clusterLogging",
):
    if marker not in cidr_script:
        raise SystemExit(f"Endpoint updater can drift the logging profile: {marker}")

runtime_validator = (root / "scripts/validate-tls-dns-security-aws.sh").read_text()
if "EXPECTED_LOG_TYPES_JSON" not in runtime_validator or "controllerManager" not in runtime_validator:
    raise SystemExit("Live security validation does not require production-parity logging")

print("EKS control-plane logging profile contracts passed.")
PY
