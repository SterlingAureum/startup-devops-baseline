#!/usr/bin/env bash
set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DEPLOYMENT="${DEMO_DEPLOYMENT:-demo-api}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-1200}"
POLL_SECONDS="${POLL_SECONDS:-5}"
RELOAD_MODE="${POSTGRESQL_WORKLOAD_RELOAD_MODE:-healthy}"

for command in aws jq kubectl python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before reloading a credential consumer." >&2
  exit 1
fi

if [[ "${CONFIRM_POSTGRESQL_WORKLOAD_RELOAD:-}" != "reload-current-secret" ]]; then
  cat >&2 <<'EOF'
This guarded operation replaces one demo-api Pod at a time without changing
the Deployment Pod template. Each replacement must load the expected Secret
digest and connect to PostgreSQL before the next Pod is deleted.

Re-run through the activation or rollback workflow, or explicitly set:
  CONFIRM_POSTGRESQL_WORKLOAD_RELOAD=reload-current-secret
  EXPECTED_DATABASE_URL_SHA256=<sha256>
EOF
  exit 1
fi

if [[ ! "${EXPECTED_DATABASE_URL_SHA256:-}" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "EXPECTED_DATABASE_URL_SHA256 must be a 64-character SHA-256 digest." >&2
  exit 1
fi

case "${RELOAD_MODE}" in
  healthy|credential-transition)
    ;;
  *)
    echo "POSTGRESQL_WORKLOAD_RELOAD_MODE must be healthy or credential-transition." >&2
    exit 1
    ;;
esac

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

is_ready() {
  jq -e '
    .status.phase == "Running" and
    any(.status.conditions[]?; .type == "Ready" and .status == "True")
  ' >/dev/null
}

pod_environment_digest() {
  local pod_name="$1"

  kubectl exec \
    --namespace "${DEMO_NAMESPACE}" \
    "${pod_name}" -- \
    python -c \
      'import hashlib, os; print(hashlib.sha256(os.environ["DATABASE_URL"].encode()).hexdigest())'
}

pod_database_health() {
  local pod_name="$1"
  local primary_ip="$2"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local health_json health_contract

  while true; do
    health_json="$(
      kubectl exec \
        --namespace "${DEMO_NAMESPACE}" \
        "${pod_name}" -- \
        python -c \
          'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/db/health", timeout=15).read().decode())' \
        2>/dev/null || true
    )"
    health_contract="$(
      jq -r '
        [
          .status // "",
          .database // "",
          .user // "",
          ((.server_address // "") | split("/")[0]),
          (.server_port // "" | tostring),
          (.in_recovery | tostring)
        ] | join(":")
      ' <<<"${health_json:-{}}" 2>/dev/null || true
    )"

    if [[ "${health_contract}" == "ok:app:app:${primary_ip}:5432:false" ]]; then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      echo "demo-api Pod ${pod_name} did not connect with the expected credential." >&2
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

deployment_json="$(
  kubectl get deployment "${DEMO_DEPLOYMENT}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
desired_replicas="$(jq -er '.spec.replicas | select(. >= 2)' <<<"${deployment_json}")" || {
  echo "demo-api must have at least two desired replicas before credential reload." >&2
  exit 1
}
ready_replicas="$(jq -r '.status.readyReplicas // 0' <<<"${deployment_json}")"
available_replicas="$(jq -r '.status.availableReplicas // 0' <<<"${deployment_json}")"
updated_replicas="$(jq -r '.status.updatedReplicas // 0' <<<"${deployment_json}")"
if (( updated_replicas != desired_replicas )); then
  echo "demo-api does not have the complete current Deployment revision." >&2
  exit 1
fi
if [[ "${RELOAD_MODE}" == "healthy" ]] && \
   (( ready_replicas != desired_replicas || available_replicas != desired_replicas )); then
  echo "demo-api is not fully Ready and Available before credential reload." >&2
  exit 1
fi

selector="$(
  jq -r '
    .spec.selector.matchLabels
    | to_entries
    | map("\(.key)=\(.value)")
    | join(",")
  ' <<<"${deployment_json}"
)"
[[ -n "${selector}" ]] || {
  echo "demo-api Deployment selector is empty." >&2
  exit 1
}

echo "==> Resolving the current PostgreSQL primary"
mapfile -t primary_pods < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#primary_pods[@]} != 1 )); then
  echo "Expected exactly one running PostgreSQL primary." >&2
  exit 1
fi
primary_ip="$(
  kubectl get pod "${primary_pods[0]}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.podIP}'
)"
[[ -n "${primary_ip}" ]] || {
  echo "The PostgreSQL primary Pod IP is empty." >&2
  exit 1
}

pods_json="$(
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "${selector}" \
    --output json
)"
mapfile -t original_pods < <(jq -r '.items[].metadata.name' <<<"${pods_json}" | sort)
if (( ${#original_pods[@]} != desired_replicas )); then
  echo "Expected ${desired_replicas} demo-api Pods, found ${#original_pods[@]}." >&2
  exit 1
fi
if ! jq -e --argjson count "${desired_replicas}" '
  (.items | length) == $count and
  all(.items[]; .status.phase == "Running" and (.metadata.deletionTimestamp == null))
' <<<"${pods_json}" >/dev/null; then
  echo "Every original demo-api Pod must exist, be Running, and not be terminating." >&2
  exit 1
fi
if [[ "${RELOAD_MODE}" == "healthy" ]] && ! jq -e '
  all(.items[];
    any(.status.conditions[]?; .type == "Ready" and .status == "True")
  )
' <<<"${pods_json}" >/dev/null; then
  echo "Every original demo-api Pod must be Ready in healthy reload mode." >&2
  exit 1
fi

echo "==> Replacing demo-api Pods one at a time"
declare -A known_uids=()
declare -A verified_replacement_uids=()
while IFS=$'\t' read -r pod_name pod_uid; do
  known_uids["${pod_uid}"]="${pod_name}"
done < <(jq -r '.items[] | [.metadata.name, .metadata.uid] | @tsv' <<<"${pods_json}")

for old_pod in "${original_pods[@]}"; do
  old_uid="$(
    kubectl get pod "${old_pod}" \
      --namespace "${DEMO_NAMESPACE}" \
      --output jsonpath='{.metadata.uid}'
  )"
  echo "==> Deleting ${old_pod}; waiting for exactly one verified replacement"
  kubectl delete pod "${old_pod}" \
    --namespace "${DEMO_NAMESPACE}" \
    --wait=false >/dev/null

  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  replacement_pod=""
  replacement_uid=""
  while true; do
    pods_json="$(
      kubectl get pods \
        --namespace "${DEMO_NAMESPACE}" \
        --selector "${selector}" \
        --output json
    )"

    if [[ "${RELOAD_MODE}" == "healthy" ]]; then
      current_available="$(
        kubectl get deployment "${DEMO_DEPLOYMENT}" \
          --namespace "${DEMO_NAMESPACE}" \
          --output jsonpath='{.status.availableReplicas}'
      )"
      current_available="${current_available:-0}"
      if (( current_available < desired_replicas - 1 )); then
        echo "demo-api availability fell below the healthy one-at-a-time reload contract." >&2
        exit 1
      fi
    else
      for verified_uid in "${!verified_replacement_uids[@]}"; do
        verified_json="$(
          jq -c --arg uid "${verified_uid}" \
            '.items[] | select(.metadata.uid == $uid)' <<<"${pods_json}"
        )"
        if [[ -z "${verified_json}" ]] || ! is_ready <<<"${verified_json}"; then
          echo "A previously verified replacement Pod lost readiness during credential transition." >&2
          exit 1
        fi
      done
    fi

    while IFS=$'\t' read -r candidate_name candidate_uid; do
      if [[ -z "${known_uids[${candidate_uid}]+present}" ]]; then
        candidate_json="$(jq -c --arg uid "${candidate_uid}" '.items[] | select(.metadata.uid == $uid)' <<<"${pods_json}")"
        if is_ready <<<"${candidate_json}"; then
          replacement_pod="${candidate_name}"
          replacement_uid="${candidate_uid}"
          break
        fi
      fi
    done < <(jq -r '.items[] | [.metadata.name, .metadata.uid] | @tsv' <<<"${pods_json}")

    if [[ -n "${replacement_pod}" ]] && \
       (( $(jq '.items | length' <<<"${pods_json}") == desired_replicas )); then
      break
    fi
    if (( SECONDS >= deadline )); then
      kubectl describe deployment "${DEMO_DEPLOYMENT}" \
        --namespace "${DEMO_NAMESPACE}" >&2 || true
      kubectl get pods --namespace "${DEMO_NAMESPACE}" \
        --selector "${selector}" --output wide >&2 || true
      echo "Timed out waiting for a Ready replacement for ${old_pod}." >&2
      exit 1
    fi
    sleep "${POLL_SECONDS}"
  done

  if [[ "$(pod_environment_digest "${replacement_pod}")" != \
        "${EXPECTED_DATABASE_URL_SHA256}" ]]; then
    echo "Replacement Pod ${replacement_pod} did not load the expected Secret digest." >&2
    exit 1
  fi
  pod_database_health "${replacement_pod}" "${primary_ip}"
  known_uids["${replacement_uid}"]="${replacement_pod}"
  verified_replacement_uids["${replacement_uid}"]="${replacement_pod}"
  unset "known_uids[${old_uid}]"
done

echo "==> Verifying the complete replacement set"
kubectl rollout status "deployment/${DEMO_DEPLOYMENT}" \
  --namespace "${DEMO_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT_SECONDS}s"
pods_json="$(
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "${selector}" \
    --output json
)"
if (( $(jq '.items | length' <<<"${pods_json}") != desired_replicas )); then
  echo "The final demo-api Pod count does not match the Deployment." >&2
  exit 1
fi

while IFS= read -r pod_name; do
  if [[ "$(pod_environment_digest "${pod_name}")" != \
        "${EXPECTED_DATABASE_URL_SHA256}" ]]; then
    echo "Final Pod ${pod_name} does not contain the expected credential digest." >&2
    exit 1
  fi
  pod_database_health "${pod_name}" "${primary_ip}"
done < <(jq -r '.items[].metadata.name' <<<"${pods_json}" | sort)

echo "demo-api PostgreSQL credential workload reload passed."
echo "Every original Pod was replaced one at a time without changing the Deployment template."
