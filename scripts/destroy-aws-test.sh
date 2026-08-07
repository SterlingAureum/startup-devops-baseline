#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="aws-test" exec "${ROOT_DIR}/scripts/destroy-aws-dev.sh"
