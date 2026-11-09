#!/usr/bin/env bash

# Shared Argo CD Application operation serialization helpers.
# The calling script must provide ARGOCD_NAMESPACE and may override the
# bounded wait and retry settings below through environment variables.

WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"
APPLICATION_IDLE_OBSERVATIONS="${APPLICATION_IDLE_OBSERVATIONS:-3}"
OPERATION_BUSY_MAX_ATTEMPTS="${OPERATION_BUSY_MAX_ATTEMPTS:-5}"
OPERATION_RETRY_DELAY_SECONDS="${OPERATION_RETRY_DELAY_SECONDS:-2}"
APPLICATION_SYNC_POLL_SECONDS="${APPLICATION_SYNC_POLL_SECONDS:-2}"
OPERATION_BUSY_MESSAGE="another operation is already in progress"

validate_argocd_operation_settings() {
  local setting_name
  local setting_value

  for setting_name in \
    WAIT_TIMEOUT_SECONDS \
    APPLICATION_IDLE_OBSERVATIONS \
    OPERATION_BUSY_MAX_ATTEMPTS; do
    setting_value="${!setting_name}"
    if ! [[ "${setting_value}" =~ ^[1-9][0-9]*$ ]]; then
      echo "ERROR: ${setting_name} must be a positive integer." >&2
      return 1
    fi
  done

  if ! [[ "${OPERATION_RETRY_DELAY_SECONDS}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: OPERATION_RETRY_DELAY_SECONDS must be a non-negative integer." >&2
    return 1
  fi
  if ! [[ "${APPLICATION_SYNC_POLL_SECONDS}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: APPLICATION_SYNC_POLL_SECONDS must be a non-negative integer." >&2
    return 1
  fi
}

argocd_application_diagnostics() {
  local application_name="$1"

  echo "Argo CD Application/${application_name} operation diagnostics:" >&2
  kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" \
    -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase,MESSAGE:.status.operationState.message' \
    >&2 || true
}

wait_for_application_sync_identity() {
  local application_name="$1"
  local expected_revision="$2"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local sync_status
  local sync_revision

  while [ "${SECONDS}" -lt "${deadline}" ]; do
    sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.status}')"
    sync_revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.revision}')"
    if [ "${sync_status}" = "Synced" ] && [ "${sync_revision}" = "${expected_revision}" ]; then
      return 0
    fi
    sleep "${APPLICATION_SYNC_POLL_SECONDS}"
  done

  echo "ERROR: Application/${application_name} did not converge to Synced revision ${expected_revision}." >&2
  argocd_application_diagnostics "${application_name}"
  return 1
}

wait_for_application_idle() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local idle_observations=0
  local operation
  local phase
  local remaining

  while [ "${SECONDS}" -lt "${deadline}" ]; do
    operation="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.operation}' 2>/dev/null || true)"
    phase="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.operationState.phase}' 2>/dev/null || true)"

    if [ -z "${operation}" ] && [ "${phase}" != "Running" ]; then
      idle_observations=$((idle_observations + 1))
      if [ "${idle_observations}" -ge "${APPLICATION_IDLE_OBSERVATIONS}" ]; then
        return 0
      fi
      sleep 1
      continue
    fi

    idle_observations=0
    remaining=$((deadline - SECONDS))
    if [ "${remaining}" -gt 0 ]; then
      argocd app wait "${application_name}" \
        --operation \
        --timeout "${remaining}" >/dev/null 2>&1 || true
    fi
    sleep 1
  done

  echo "ERROR: timed out waiting for Application/${application_name} to become idle." >&2
  argocd_application_diagnostics "${application_name}"
  return 1
}

run_argocd_mutation_with_retry() {
  local application_name="$1"
  shift

  local attempt
  local command_output
  local command_status

  for ((attempt = 1; attempt <= OPERATION_BUSY_MAX_ATTEMPTS; attempt++)); do
    if command_output="$("$@" 2>&1)"; then
      command_status=0
    else
      command_status=$?
    fi

    if [ "${command_status}" -eq 0 ]; then
      if [ -n "${command_output}" ]; then
        printf '%s\n' "${command_output}"
      fi
      return 0
    fi

    if ! grep -Fq "${OPERATION_BUSY_MESSAGE}" <<<"${command_output}"; then
      printf '%s\n' "${command_output}" >&2
      return "${command_status}"
    fi

    echo "Application/${application_name} is operation-busy (attempt ${attempt}/${OPERATION_BUSY_MAX_ATTEMPTS}); waiting before retry." >&2

    if [ "${attempt}" -ge "${OPERATION_BUSY_MAX_ATTEMPTS}" ]; then
      printf '%s\n' "${command_output}" >&2
      echo "ERROR: Application/${application_name} remained operation-busy after ${OPERATION_BUSY_MAX_ATTEMPTS} attempts." >&2
      argocd_application_diagnostics "${application_name}"
      return 1
    fi

    wait_for_application_idle "${application_name}"
    sleep "${OPERATION_RETRY_DELAY_SECONDS}"
  done
}
