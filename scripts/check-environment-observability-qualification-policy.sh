#!/usr/bin/env bash
set -Eeuo pipefail

QUALIFICATION_ENVIRONMENT="${QUALIFICATION_ENVIRONMENT:-}"
QUALIFICATION_ACTION="${QUALIFICATION_ACTION:-}"
APPROVED_PRODUCTION_OBSERVATION="${APPROVED_PRODUCTION_OBSERVATION:-false}"

fail() { echo "ERROR: $*" >&2; exit 1; }

case "${QUALIFICATION_ENVIRONMENT}" in
  local|aws-dev|aws-test|aws-prod) ;;
  *) fail "QUALIFICATION_ENVIRONMENT must be one of: local, aws-dev, aws-test, aws-prod" ;;
esac

case "${QUALIFICATION_ACTION}" in
  validate-identity|observe|collect-evidence) ;;
  apply|patch|delete|sync|promote|abort|retry|restart|generate-traffic|synthetic-alert|fault-inject|create-environment|destroy-environment)
    fail "v0.11.8 qualification forbids runtime action: ${QUALIFICATION_ACTION}"
    ;;
  *) fail "unknown QUALIFICATION_ACTION: ${QUALIFICATION_ACTION:-<empty>}" ;;
esac

if [ "${QUALIFICATION_ENVIRONMENT}" = aws-prod ] && [ "${APPROVED_PRODUCTION_OBSERVATION}" != true ]; then
  fail "aws-prod observation requires APPROVED_PRODUCTION_OBSERVATION=true"
fi

echo "v0.11.8 policy approved ${QUALIFICATION_ACTION} for ${QUALIFICATION_ENVIRONMENT}."
