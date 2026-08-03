#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALUES_FILE="${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml"
ENV_VARIABLES="${ROOT_DIR}/infra/terraform/aws/environments/dev/variables.tf"
ENV_MAIN="${ROOT_DIR}/infra/terraform/aws/environments/dev/main.tf"
EKS_MAIN="${ROOT_DIR}/infra/terraform/aws/modules/eks/main.tf"
TLS_MAIN="${ROOT_DIR}/infra/terraform/aws/modules/tls-dns/main.tf"
APPLY_SCRIPT="${ROOT_DIR}/scripts/apply-eks-api-access-cidr.sh"
DEPLOY_SCRIPT="${ROOT_DIR}/scripts/deploy-aws-dev-root-app.sh"
DNS_SCRIPT="${ROOT_DIR}/scripts/reconcile-demo-api-dns.sh"
FINAL_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.8-final.sh"
ACTIVATION_VALIDATOR="${ROOT_DIR}/scripts/validate-postgresql-credential-activation-aws.sh"

for command in git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 - \
  "${VALUES_FILE}" "${ENV_VARIABLES}" "${ENV_MAIN}" \
  "${EKS_MAIN}" "${TLS_MAIN}" "${APPLY_SCRIPT}" "${DEPLOY_SCRIPT}" \
  "${DNS_SCRIPT}" "${FINAL_VALIDATOR}" "${ACTIVATION_VALIDATOR}" <<'PY'
from pathlib import Path
import sys

(
    values,
    variables,
    env_main,
    eks_main,
    tls_main,
    apply_script,
    deploy_script,
    dns_script,
    final_validator,
    activation_validator,
) = [
    Path(path).read_text() for path in sys.argv[1:]
]

required_values = [
    'alb.ingress.kubernetes.io/listen-ports: \'[{"HTTP":80},{"HTTPS":443}]\'',
    'alb.ingress.kubernetes.io/ssl-redirect: "443"',
    'alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06',
    'host: demo.dev.aureumstack.com',
]
for marker in required_values:
    if marker not in values:
        raise SystemExit(f"Missing HTTPS Ingress contract: {marker}")

for marker in [
    'default     = []',
    '!contains(var.eks_public_access_cidrs, "0.0.0.0/0")',
    'default     = ["api", "audit", "authenticator"]',
    'default     = 14',
    'default     = "aureumstack.com"',
    'default     = "demo.dev.aureumstack.com"',
]:
    if marker not in variables:
        raise SystemExit(f"Missing environment hardening contract: {marker}")

for marker in ['module "tls_dns"', 'cluster_log_retention_days']:
    if marker not in env_main:
        raise SystemExit(f"Missing Terraform environment contract: {marker}")

for marker in [
    'resource "aws_cloudwatch_log_group" "cluster"',
    '!contains(var.public_access_cidrs, "0.0.0.0/0")',
    'aws_cloudwatch_log_group.cluster',
]:
    if marker not in eks_main:
        raise SystemExit(f"Missing EKS hardening contract: {marker}")

for marker in [
    'resource "aws_acm_certificate" "demo_api"',
    'resource "aws_route53_record" "certificate_validation"',
    'resource "aws_acm_certificate_validation" "demo_api"',
]:
    if marker not in tls_main:
        raise SystemExit(f"Missing TLS/DNS Terraform contract: {marker}")

for marker in [
    'MANAGEMENT_PUBLIC_IP',
    'umask 077',
    'mktemp',
    '-var="eks_public_access_cidrs=',
    '-var="eks_enabled_cluster_log_types=',
    'rm -f -- "${PLAN_FILE}"',
    'aws eks wait cluster-active',
    'aws eks update-kubeconfig',
    'kubectl --request-timeout=30s get --raw=/readyz',
]:
    if marker not in apply_script:
        raise SystemExit(f"Missing runtime-only CIDR contract: {marker}")

for marker in [
    'aws eks update-kubeconfig',
    'kubectl --request-timeout=30s get --raw=/readyz',
    'RECONCILE_DEMO_API_DNS_SCRIPT',
    'Reconciling the stable demo-api hostname to the live ALB',
]:
    if marker not in deploy_script:
        raise SystemExit(f"Missing rebuild-safe deployment contract: {marker}")

for marker in [
    'ALB_WAIT_SECONDS',
    'Waiting for the Ingress ALB hostname',
    'Waiting for the ALB API identity',
    'Action: "UPSERT"',
]:
    if marker not in dns_script:
        raise SystemExit(f"Missing rebuild-safe DNS contract: {marker}")

runtime_call = 'scripts/validate-tls-dns-security-aws.sh'
rollback_call = 'scripts/validate-postgresql-credential-rollback-aws.sh'
if runtime_call not in final_validator or rollback_call not in final_validator:
    raise SystemExit("The v0.8 final validator is missing a required runtime check.")
if final_validator.index(runtime_call) > final_validator.index(rollback_call):
    raise SystemExit("AWS TLS/DNS runtime validation must precede credential final-state validation.")

for marker in [
    'normal initial state for a rebuilt environment',
    'V0.8.5_POSTGRESQL_CREDENTIAL_ROTATION.md',
]:
    if marker not in activation_validator:
        raise SystemExit(f"Missing rebuilt-credential diagnostic: {marker}")
PY

GIT_ROOT="$(git -C "${ROOT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ "${GIT_ROOT}" == "${ROOT_DIR}" ]]; then
  python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import ipaddress
import re
import subprocess
import sys

root = Path(sys.argv[1])
tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-z"],
    check=True,
    capture_output=True,
).stdout.decode().split("\0")
assignment = re.compile(r"(?:eks_public_access_cidrs|TF_VAR_eks_public_access_cidrs)\s*=")
cidr_pattern = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32(?![0-9])")

for relative in tracked:
    if not relative:
        continue
    path = root / relative
    if not path.is_file():
        continue
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if not assignment.search(line):
            continue
        for value in cidr_pattern.findall(line):
            address = ipaddress.ip_network(value, strict=True).network_address
            if address.is_global:
                raise SystemExit(
                    f"Tracked management public CIDR found in {relative}:{number}; "
                    "remove it and use apply-eks-api-access-cidr.sh"
                )
PY
fi

echo "TLS, DNS, EKS endpoint, logging, and public-IP privacy contracts passed."
