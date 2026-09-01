#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${CONFIRM_AWS_DEV_APPLY:-}" == create-ephemeral-aws-dev ]] || {
  echo 'Creates billable AWS resources. Set CONFIRM_AWS_DEV_APPLY=create-ephemeral-aws-dev.' >&2
  exit 1
}
[[ "${AWS_ENVIRONMENT:-aws-dev}" == aws-dev ]] || exit 1
export AWS_ENVIRONMENT=aws-dev EKS_ACCESS_MODE=create-dev
export CONFIRM_EKS_API_CIDR_UPDATE=restrict-current-ip
export EKS_CLUSTER_LOG_TYPES_JSON="${EKS_CLUSTER_LOG_TYPES_JSON:-[]}"
exec "${ROOT_DIR}/scripts/apply-eks-api-access-cidr.sh"
