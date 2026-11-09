#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
RENDER_KUSTOMIZE="${RENDER_KUSTOMIZE:-true}"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" <<'PY'
from ipaddress import ip_network
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
terraform_root = root / "infra/terraform/aws/environments"
cluster_root = root / "clusters/aws"

profiles = {
    "dev": {
        "aws_environment": "aws-dev",
        "vpc": "10.20.0.0/16",
        "public": ("10.20.0.0/24", "10.20.1.0/24"),
        "private": ("10.20.10.0/24", "10.20.11.0/24"),
        "service": "172.20.0.0/16",
        "hostname": "demo.dev.aureumstack.com",
        "log_types": (),
        "logs": "14",
        "force_destroy": "true",
        "secret_recovery": "0",
        "single_nat": "true",
    },
    "test": {
        "aws_environment": "aws-test",
        "vpc": "10.30.0.0/16",
        "public": ("10.30.0.0/24", "10.30.1.0/24"),
        "private": ("10.30.10.0/24", "10.30.11.0/24"),
        "service": "172.21.0.0/16",
        "hostname": "demo.test.aureumstack.com",
        "log_types": (),
        "logs": "30",
        "force_destroy": "true",
        "secret_recovery": "7",
        "single_nat": "true",
    },
    "prod": {
        "aws_environment": "aws-prod",
        "vpc": "10.40.0.0/16",
        "public": ("10.40.0.0/24", "10.40.1.0/24"),
        "private": ("10.40.10.0/24", "10.40.11.0/24"),
        "service": "172.22.0.0/16",
        "hostname": "demo.prod.aureumstack.com",
        "log_types": (
            "api", "audit", "authenticator", "controllerManager", "scheduler"
        ),
        "logs": "90",
        "force_destroy": "false",
        "secret_recovery": "30",
        "single_nat": "false",
    },
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


def scalar_default(text: str, name: str) -> str:
    block = variable_block(text, name)
    match = re.search(r"(?m)^\s*default\s*=\s*(.+?)\s*$", block)
    if not match:
        raise SystemExit(f"Missing default for Terraform variable: {name}")
    return match.group(1).strip().strip('"')


def list_default(text: str, name: str) -> tuple[str, ...]:
    block = variable_block(text, name)
    match = re.search(r"default\s*=\s*\[(.*?)\]", block, re.DOTALL)
    if not match:
        raise SystemExit(f"Missing list default for Terraform variable: {name}")
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


required_tf_files = {
    "backend.tf", "main.tf", "outputs.tf", "providers.tf",
    "terraform.tfvars.example", "variables.tf", "versions.tf",
}
vpc_networks = []
service_networks = []
hostnames = set()

for environment, expected in profiles.items():
    environment_dir = terraform_root / environment
    actual_files = {path.name for path in environment_dir.glob("*.tf*") if path.is_file()}
    missing = sorted(required_tf_files - actual_files)
    if missing:
        raise SystemExit(f"{environment}: missing Terraform files: {missing}")

    variables = (environment_dir / "variables.tf").read_text()
    main = (environment_dir / "main.tf").read_text()
    backend = (environment_dir / "backend.tf").read_text()
    tfvars = (environment_dir / "terraform.tfvars.example").read_text()

    scalar_expectations = {
        "environment": environment,
        "vpc_cidr": expected["vpc"],
        "eks_service_ipv4_cidr": expected["service"],
        "demo_api_hostname": expected["hostname"],
        "eks_cluster_log_retention_days": expected["logs"],
        "cnpg_backup_force_destroy": expected["force_destroy"],
        "external_secrets_recovery_window_in_days": expected["secret_recovery"],
        "single_nat_gateway": expected["single_nat"],
    }
    for variable, value in scalar_expectations.items():
        actual = scalar_default(variables, variable)
        if actual != value:
            raise SystemExit(
                f"{environment}: {variable} default is {actual!r}, expected {value!r}"
            )

    if list_default(variables, "public_subnet_cidrs") != expected["public"]:
        raise SystemExit(f"{environment}: public subnet defaults do not match the address plan")
    if list_default(variables, "private_subnet_cidrs") != expected["private"]:
        raise SystemExit(f"{environment}: private subnet defaults do not match the address plan")
    if list_default(variables, "eks_enabled_cluster_log_types") != expected["log_types"]:
        raise SystemExit(f"{environment}: EKS logging default does not match the cost profile")
    if f'var.environment == "{environment}"' not in variable_block(variables, "environment"):
        raise SystemExit(f"{environment}: root does not lock its environment identity")
    if 'cluster_name = "${var.project_name}-${var.environment}"' not in main:
        raise SystemExit(f"{environment}: cluster naming is not derived from the locked environment")
    if "workspace" in backend.lower():
        raise SystemExit(f"{environment}: Terraform CLI workspaces must not isolate environments")
    if f'environment  = "{environment}"' not in tfvars:
        raise SystemExit(f"{environment}: example tfvars does not identify its own environment")

    vpc = ip_network(expected["vpc"])
    service = ip_network(expected["service"])
    for subnet in (*expected["public"], *expected["private"]):
        if not ip_network(subnet).subnet_of(vpc):
            raise SystemExit(f"{environment}: subnet {subnet} is outside {vpc}")
    vpc_networks.append((environment, vpc))
    service_networks.append((environment, service))
    if expected["hostname"] in hostnames:
        raise SystemExit(f"Duplicate demo-api hostname: {expected['hostname']}")
    hostnames.add(expected["hostname"])

for networks, label in ((vpc_networks, "VPC"), (service_networks, "Service")):
    for index, (left_name, left) in enumerate(networks):
        for right_name, right in networks[index + 1:]:
            if left.overlaps(right):
                raise SystemExit(
                    f"{label} CIDRs overlap: {left_name} {left} and {right_name} {right}"
                )

prod_variables = (terraform_root / "prod/variables.tf").read_text()
for name, marker in {
    "single_nat_gateway": "!var.single_nat_gateway",
    "cnpg_backup_force_destroy": "!var.cnpg_backup_force_destroy",
    "external_secrets_recovery_window_in_days":
        "var.external_secrets_recovery_window_in_days == 30",
    "eks_cluster_log_retention_days": "var.eks_cluster_log_retention_days >= 90",
    "eks_enabled_cluster_log_types":
        "toset(var.eks_enabled_cluster_log_types) == toset([",
}.items():
    if marker not in variable_block(prod_variables, name):
        raise SystemExit(f"prod: fail-closed validation is missing for {name}")

prod_main = (terraform_root / "prod/main.tf").read_text()
prod_outputs = (terraform_root / "prod/outputs.tf").read_text()
if 'module "fis"' in prod_main or "module.fis" in prod_outputs:
    raise SystemExit("prod: AWS FIS experiment resources must remain outside production")

if (root / "clusters/aws-dev").exists():
    raise SystemExit("Legacy clusters/aws-dev must be removed after base/overlay migration")

base_files = (
    "base/kustomization.yaml",
    "base/platform/kustomization.yaml",
    "base/data-platform/postgresql/kustomization.yaml",
    "base/security/external-secrets/startup-apps/kustomization.yaml",
    "base/security/network-policies/data-platform/kustomization.yaml",
    "base/security/network-policies/startup-apps/kustomization.yaml",
)
for relative in base_files:
    if not (cluster_root / relative).is_file():
        raise SystemExit(f"Missing AWS Kustomize base declaration: {relative}")

for environment, expected in profiles.items():
    overlay = cluster_root / "overlays" / environment
    required = (
        "root-app.yaml",
        "kustomization.yaml",
        "data-platform/postgresql/kustomization.yaml",
        "security/external-secrets/startup-apps/kustomization.yaml",
        "security/network-policies/data-platform/kustomization.yaml",
        "security/network-policies/startup-apps/kustomization.yaml",
    )
    for relative in required:
        if not (overlay / relative).is_file():
            raise SystemExit(f"{environment}: missing overlay declaration {relative}")
    root_app = (overlay / "root-app.yaml").read_text()
    for marker in (
        f"name: startup-devops-aws-{environment}-root",
        "targetRevision: main",
        f"path: clusters/aws/overlays/{environment}",
        "RespectIgnoreDifferences=true",
    ):
        if marker not in root_app:
            raise SystemExit(f"{environment}: root Application is missing {marker}")

for path in cluster_root.rglob("*.yaml"):
    text = path.read_text()
    if "clusters/aws-dev" in text:
        raise SystemExit(f"{path.relative_to(root)}: legacy AWS GitOps path remains")

print("AWS environment declaration static validation passed.")
PY

if [[ "${RENDER_KUSTOMIZE}" != "true" ]]; then
  echo "Kustomize rendering skipped because RENDER_KUSTOMIZE=${RENDER_KUSTOMIZE}."
  exit 0
fi

if command -v kustomize >/dev/null 2>&1; then
  render() {
    kustomize build "$1"
  }
elif command -v kubectl >/dev/null 2>&1; then
  render() {
    kubectl kustomize "$1"
  }
else
  echo "kustomize or kubectl is required for AWS overlay rendering" >&2
  exit 1
fi

for environment in dev test prod; do
  overlay="${ROOT_DIR}/clusters/aws/overlays/${environment}"
  rendered="${WORK_DIR}/${environment}-platform.yaml"
  render "${overlay}" >"${rendered}"

  grep -F "startup-devops-baseline-${environment}" "${rendered}" >/dev/null || {
    echo "${environment}: rendered platform does not contain its cluster identity" >&2
    exit 1
  }
  grep -F "values/environments/aws-${environment}.yaml" "${rendered}" >/dev/null
  grep -F "values/releases/aws-${environment}.yaml" "${rendered}" >/dev/null
  grep -F "clusters/aws/overlays/${environment}/data-platform/postgresql" "${rendered}" >/dev/null
  grep -F "clusters/aws/overlays/${environment}/security/external-secrets/startup-apps" "${rendered}" >/dev/null

  case "${environment}" in
    dev|test)
      grep -F "name: runtime-qualification-rbac-aws-${environment}" "${rendered}" >/dev/null || {
        echo "${environment}: rendered platform is missing runtime qualification RBAC" >&2
        exit 1
      }
      ;;
    prod)
      if grep -F "runtime-qualification-rbac" "${rendered}" >/dev/null; then
        echo "prod: rendered platform contains runtime qualification RBAC" >&2
        exit 1
      fi
      ;;
  esac

  render "${overlay}/data-platform/postgresql" \
    >"${WORK_DIR}/${environment}-postgresql.yaml"
  render "${overlay}/security/external-secrets/startup-apps" \
    >"${WORK_DIR}/${environment}-external-secrets.yaml"
  render "${overlay}/security/network-policies/data-platform" \
    >"${WORK_DIR}/${environment}-data-network-policy.yaml"
  render "${overlay}/security/network-policies/startup-apps" \
    >"${WORK_DIR}/${environment}-startup-network-policy.yaml"

  grep -F "startup-devops-baseline-${environment}/demo-api/postgresql" \
    "${WORK_DIR}/${environment}-external-secrets.yaml" >/dev/null

  case "${environment}" in
    dev) vpc_prefix="10.20"; service_prefix="172.20" ;;
    test) vpc_prefix="10.30"; service_prefix="172.21" ;;
    prod) vpc_prefix="10.40"; service_prefix="172.22" ;;
  esac
  grep -F "${vpc_prefix}.0.0/24" \
    "${WORK_DIR}/${environment}-startup-network-policy.yaml" >/dev/null
  grep -F "${vpc_prefix}.10.0/24" \
    "${WORK_DIR}/${environment}-data-network-policy.yaml" >/dev/null
  grep -F "${service_prefix}.0.0/16" \
    "${WORK_DIR}/${environment}-data-network-policy.yaml" >/dev/null

  case "${environment}" in
    dev) forbidden_pattern='aws-(test|prod)|baseline-(test|prod)|10\.(30|40)\.|172\.(21|22)\.' ;;
    test) forbidden_pattern='aws-(dev|prod)|baseline-(dev|prod)|10\.(20|40)\.|172\.(20|22)\.' ;;
    prod) forbidden_pattern='aws-(dev|test)|baseline-(dev|test)|10\.(20|30)\.|172\.(20|21)\.' ;;
  esac
  if grep -E "${forbidden_pattern}" \
    "${rendered}" \
    "${WORK_DIR}/${environment}-postgresql.yaml" \
    "${WORK_DIR}/${environment}-external-secrets.yaml" \
    "${WORK_DIR}/${environment}-data-network-policy.yaml" \
    "${WORK_DIR}/${environment}-startup-network-policy.yaml" >/dev/null; then
    echo "${environment}: rendered manifests contain another environment's identity" >&2
    exit 1
  fi
done

if grep -F "application-spot-fis" "${WORK_DIR}/prod-platform.yaml" >/dev/null; then
  echo "prod: rendered platform contains FIS-only Karpenter capacity" >&2
  exit 1
fi

echo "AWS dev/test/prod Kustomize rendering passed."
