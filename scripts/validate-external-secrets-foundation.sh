#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

readonly MODULE_DIR="${ROOT_DIR}/infra/terraform/aws/modules/external-secrets"
readonly ENVIRONMENT_DIR="${ROOT_DIR}/infra/terraform/aws/environments/dev"
readonly ARCHIVE_DOC="${ROOT_DIR}/docs/archive/V0.8.3_EXTERNAL_SECRETS_FOUNDATION.md"

for path in \
  "${MODULE_DIR}/main.tf" \
  "${MODULE_DIR}/variables.tf" \
  "${MODULE_DIR}/outputs.tf" \
  "${MODULE_DIR}/README.md" \
  "${ENVIRONMENT_DIR}/main.tf" \
  "${ENVIRONMENT_DIR}/variables.tf" \
  "${ENVIRONMENT_DIR}/outputs.tf" \
  "${ENVIRONMENT_DIR}/terraform.tfvars.example" \
  "${ARCHIVE_DOC}"; do
  [[ -f "${path}" ]] || {
    echo "Required External Secrets foundation file is missing: ${path}" >&2
    exit 1
  }
done

python3 - \
  "${MODULE_DIR}/main.tf" \
  "${MODULE_DIR}/variables.tf" \
  "${MODULE_DIR}/outputs.tf" \
  "${ENVIRONMENT_DIR}/main.tf" \
  "${ENVIRONMENT_DIR}/variables.tf" \
  "${ENVIRONMENT_DIR}/outputs.tf" \
  "${ENVIRONMENT_DIR}/terraform.tfvars.example" \
  "${ARCHIVE_DOC}" <<'PY'
from pathlib import Path
import sys

(
    module_main_path,
    module_variables_path,
    module_outputs_path,
    environment_main_path,
    environment_variables_path,
    environment_outputs_path,
    tfvars_path,
    archive_path,
) = map(Path, sys.argv[1:])

module_main = module_main_path.read_text()
module_variables = module_variables_path.read_text()
module_outputs = module_outputs_path.read_text()
environment_main = environment_main_path.read_text()
environment_variables = environment_variables_path.read_text()
environment_outputs = environment_outputs_path.read_text()
tfvars = tfvars_path.read_text()
archive = archive_path.read_text()


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise SystemExit(f"{label} is missing: {marker}")


require(
    module_main,
    'resource "aws_secretsmanager_secret" "this"',
    "Secrets Manager container",
)
require(
    module_main,
    'secret_name = "${local.name_prefix}/demo-api/postgresql"',
    "deterministic secret name",
)
require(
    module_main,
    "recovery_window_in_days = var.recovery_window_in_days",
    "configurable secret recovery window",
)

for forbidden in (
    "aws_secretsmanager_secret_version",
    "secret_string",
    "secret_binary",
):
    if forbidden in module_main:
        raise SystemExit(
            f"Terraform must not manage secret material through {forbidden}."
        )

require(
    module_main,
    'actions = ["sts:AssumeRoleWithWebIdentity"]',
    "IRSA web-identity action",
)
require(
    module_main,
    'identifiers = [var.oidc_provider_arn]',
    "EKS OIDC trust principal",
)
require(
    module_main,
    '${replace(var.oidc_provider_url, "https://", "")}:aud',
    "IRSA audience condition",
)
require(
    module_main,
    '${replace(var.oidc_provider_url, "https://", "")}:sub',
    "IRSA subject condition",
)
require(
    module_main,
    '"system:serviceaccount:${var.service_account_namespace}:${var.service_account_name}"',
    "ServiceAccount-scoped IRSA subject",
)

expected_actions = {
    '"secretsmanager:DescribeSecret"',
    '"secretsmanager:GetSecretValue"',
}
actual_actions = {
    line.strip().rstrip(",")
    for line in module_main.splitlines()
    if '"secretsmanager:' in line
}
if actual_actions != expected_actions:
    raise SystemExit(
        "External Secrets IAM actions must be exactly DescribeSecret and "
        f"GetSecretValue; found {sorted(actual_actions)}"
    )

require(
    module_main,
    "resources = [aws_secretsmanager_secret.this.arn]",
    "single-secret IAM resource scope",
)

for forbidden_action in (
    "secretsmanager:ListSecrets",
    "secretsmanager:BatchGetSecretValue",
    "secretsmanager:CreateSecret",
    "secretsmanager:PutSecretValue",
    "secretsmanager:UpdateSecret",
    "secretsmanager:DeleteSecret",
    "secretsmanager:TagResource",
    "secretsmanager:RotateSecret",
    "kms:Decrypt",
):
    if forbidden_action in module_main:
        raise SystemExit(
            f"External Secrets read role contains forbidden action: {forbidden_action}"
        )

for marker in (
    'default     = "external-secrets"',
    "var.recovery_window_in_days == 0",
    "var.recovery_window_in_days >= 7",
    "var.recovery_window_in_days <= 30",
):
    require(module_variables, marker, "module input contract")

for output_name in (
    "secret_name",
    "secret_arn",
    "role_arn",
    "role_name",
    "policy_arn",
):
    require(
        module_outputs,
        f'output "{output_name}"',
        "module non-sensitive output contract",
    )

for marker in (
    'module "external_secrets"',
    'source = "../../modules/external-secrets"',
    "oidc_provider_arn         = module.eks.oidc_provider_arn",
    "oidc_provider_url         = module.eks.oidc_provider_url",
    'service_account_name      = "external-secrets"',
    'service_account_namespace = "external-secrets"',
    "recovery_window_in_days   = var.external_secrets_recovery_window_in_days",
):
    require(environment_main, marker, "aws-dev module wiring")

require(
    environment_variables,
    'variable "external_secrets_recovery_window_in_days"',
    "aws-dev recovery-window variable",
)
require(
    tfvars,
    "external_secrets_recovery_window_in_days = 0",
    "aws-dev recovery-window example",
)

for output_name in (
    "external_secrets_secret_name",
    "external_secrets_secret_arn",
    "external_secrets_role_arn",
    "external_secrets_role_name",
    "external_secrets_policy_arn",
):
    require(
        environment_outputs,
        f'output "{output_name}"',
        "aws-dev non-sensitive output contract",
    )

for marker in (
    "Checkpoint 1 implementation complete; AWS runtime validation pending.",
    "Secret values never enter Git or Terraform state.",
    "Checkpoint 2 must not begin until the AWS runtime validation passes.",
):
    require(archive, marker, "v0.8.3 checkpoint status and boundary")
PY

echo "External Secrets AWS foundation contract validation passed."
