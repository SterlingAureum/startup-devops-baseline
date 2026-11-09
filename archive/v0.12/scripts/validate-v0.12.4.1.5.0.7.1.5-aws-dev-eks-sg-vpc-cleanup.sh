#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py" --root "${ROOT_DIR}"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py"
python3 -m py_compile "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py" "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py" "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py"
bash -n "${ROOT_DIR}/scripts/validate-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.sh"
echo "v0.12.4.1.5.0.7.1.5 aws-dev EKS-SG/VPC cleanup validation passed offline."
