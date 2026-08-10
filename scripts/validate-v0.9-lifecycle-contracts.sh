#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
required = {
    "scripts/apply-aws-test.sh": (
        "CONFIRM_AWS_TEST_APPLY",
        "apply-ephemeral-aws-test",
        "AWS_TEST_APPLY_MODE",
        'AWS_ENVIRONMENT="aws-test"',
    ),
    "scripts/bootstrap-aws-test.sh": (
        "CONFIRM_AWS_TEST_BOOTSTRAP",
        "DEMO_ACCEPTED_HEALTH_STATUSES",
        'TARGET_REVISION="main"',
    ),
    "scripts/complete-aws-test-rollout.sh": (
        "CONFIRM_AWS_TEST_ROLLOUT",
        "promote-reviewed-aws-test",
        "currentStepIndex",
        "promotion_count > 3",
    ),
    "scripts/validate-demo-api-postgresql.sh": (
        "DEMO_WORKLOAD_KIND",
        'Rollout) workload_resource="rollout"',
        'rollout/${DEMO_DEPLOYMENT}',
    ),
    "scripts/destroy-aws-dev.sh": (
        'AWS_ENVIRONMENT}" == "aws-prod"',
        "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "EKS_PUBLIC_ACCESS_CIDRS_JSON",
        "validate-aws-cost-cleanup.sh",
    ),
    "scripts/validate-aws-cost-cleanup.sh": (
        "resourcegroupstaggingapi get-resources",
        "ec2 describe-fleets",
        "deleted_terminating",
        "InvalidFleetId\\.NotFound",
        "DescribeFleetInstances",
        "describe-nat-gateways",
        "describe-volumes",
        "elbv2.k8s.aws/cluster",
        "head-bucket",
        ".DeletedDate != null",
        "list-resource-record-sets",
    ),
}
for relative, markers in required.items():
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Missing lifecycle file: {relative}")
    text = path.read_text()
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"{relative}: missing lifecycle marker {marker}")

destroy_wrapper = (root / "scripts/destroy-aws-test.sh").read_text()
if 'AWS_ENVIRONMENT="aws-test"' not in destroy_wrapper:
    raise SystemExit("destroy-aws-test.sh must pin the disposable target")

prod_variables = (root / "infra/terraform/aws/environments/prod/variables.tf").read_text()
for marker in ('default     = false', 'var.external_secrets_recovery_window_in_days == 30'):
    if marker not in prod_variables:
        raise SystemExit("Production destruction or recovery guard regressed")

print("v0.9 lifecycle static contracts passed.")
PY

mkdir -p "${WORK_DIR}/bin" "${WORK_DIR}/tf"

cat >"${WORK_DIR}/bin/terraform" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"state list"* ]]; then
  exit 0
fi
exit 1
MOCK

cat >"${WORK_DIR}/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
service="${1:-}"
operation="${2:-}"
case "${service}:${operation}" in
  sts:get-caller-identity) echo "123456789012" ;;
  eks:describe-cluster) exit 254 ;;
  ec2:describe-instances|ec2:describe-volumes|ec2:describe-addresses|ec2:describe-vpcs)
    echo "0"
    ;;
  ec2:describe-nat-gateways)
    if [[ "${MOCK_AWS_RESIDUAL:-}" == "nat" ]]; then echo "1"; else echo "0"; fi
    ;;
  ec2:describe-fleets)
    case "${MOCK_AWS_RESIDUAL:-}" in
      fleet-terminal)
        echo '{"Fleets":[{"FleetId":"fleet-00000000-0000-0000-0000-000000000001","FleetState":"deleted_terminating","Type":"instant"}]}'
        ;;
      fleet-active)
        echo '{"Fleets":[{"FleetId":"fleet-00000000-0000-0000-0000-000000000001","FleetState":"active","Type":"instant"}]}'
        ;;
      fleet-notfound)
        echo 'An error occurred (InvalidFleetId.NotFound) when calling the DescribeFleets operation' >&2
        exit 254
        ;;
      *) echo '{"Fleets":[]}' ;;
    esac
    ;;
  s3api:head-bucket) exit 254 ;;
  secretsmanager:describe-secret) echo '{"DeletedDate":"2026-08-14T00:00:00Z"}' ;;
  logs:describe-log-groups|acm:list-certificates) echo "0" ;;
  route53:list-hosted-zones-by-name) echo "/hostedzone/ZTEST" ;;
  route53:list-resource-record-sets) echo "null" ;;
  resourcegroupstaggingapi:get-resources)
    if [[ "$*" == *"length(ResourceTagMappingList)"* ]]; then
      echo "0"
    elif [[ "${MOCK_AWS_RESIDUAL:-}" == fleet-* ]]; then
      echo '{"ResourceTagMappingList":[{"ResourceARN":"arn:aws:ec2:us-east-1:123456789012:fleet/fleet-00000000-0000-0000-0000-000000000001","Tags":[]}]}'
    else
      echo '{"ResourceTagMappingList":[]}'
    fi
    ;;
  *) echo "Unexpected mock AWS call: $*" >&2; exit 1 ;;
esac
MOCK
chmod +x "${WORK_DIR}/bin/aws" "${WORK_DIR}/bin/terraform"

PATH="${WORK_DIR}/bin:${PATH}" \
AWS_ENVIRONMENT="aws-test" \
TF_DIR="${WORK_DIR}/tf" \
  "${ROOT_DIR}/scripts/validate-aws-cost-cleanup.sh" >/dev/null

if PATH="${WORK_DIR}/bin:${PATH}" \
   AWS_ENVIRONMENT="aws-test" \
   TF_DIR="${WORK_DIR}/tf" \
   MOCK_AWS_RESIDUAL="nat" \
     "${ROOT_DIR}/scripts/validate-aws-cost-cleanup.sh" >/dev/null 2>&1; then
  echo "Cleanup audit accepted a residual NAT Gateway." >&2
  exit 1
fi

for terminal_case in fleet-terminal fleet-notfound; do
  PATH="${WORK_DIR}/bin:${PATH}" \
  AWS_ENVIRONMENT="aws-test" \
  TF_DIR="${WORK_DIR}/tf" \
  MOCK_AWS_RESIDUAL="${terminal_case}" \
    "${ROOT_DIR}/scripts/validate-aws-cost-cleanup.sh" >/dev/null
done

if PATH="${WORK_DIR}/bin:${PATH}" \
   AWS_ENVIRONMENT="aws-test" \
   TF_DIR="${WORK_DIR}/tf" \
   MOCK_AWS_RESIDUAL="fleet-active" \
     "${ROOT_DIR}/scripts/validate-aws-cost-cleanup.sh" >/dev/null 2>&1; then
  echo "Cleanup audit accepted an active EC2 Fleet." >&2
  exit 1
fi

echo "v0.9 lifecycle cleanup behavior passed."
