#!/usr/bin/env bash

observability_stop_port_forward() {
  local pid="$1"
  local log_path="$2"

  kill "${pid}" >/dev/null 2>&1 || true
  wait "${pid}" >/dev/null 2>&1 || true
  rm -f -- "${log_path}"
}

observability_print_demo_api_runtime_state() {
  local app_namespace="$1"
  local argocd_namespace="$2"
  local application_name="$3"

  echo "DIAGNOSTIC: current demo-api runtime ownership:" >&2
  kubectl -n "${app_namespace}" get rollout "${application_name}" \
    -o jsonpath='  rollout image={.spec.template.spec.containers[0].image}{"\n"}' >&2 || true
  kubectl -n "${argocd_namespace}" get application "${application_name}" \
    -o jsonpath='  target revision={.spec.source.targetRevision}{"\n"}  Helm parameters={.spec.source.helm.parameters}{"\n"}' >&2 || true
}

observability_generate_demo_api_metrics() {
  local app_namespace="$1"
  local argocd_namespace="$2"
  local application_name="$3"
  local local_port="$4"
  local request_count="${5:-12}"
  local traffic_service="${application_name}-stable"
  local traffic_log
  local traffic_pid
  local metrics_payload=""
  local ready=false

  if ! kubectl -n "${app_namespace}" get service "${traffic_service}" >/dev/null 2>&1; then
    traffic_service="${application_name}"
  fi

  traffic_log="$(mktemp)"
  kubectl -n "${app_namespace}" port-forward "service/${traffic_service}" \
    "${local_port}:80" >"${traffic_log}" 2>&1 &
  traffic_pid="$!"

  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${local_port}/health" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done

  if [ "${ready}" != "true" ]; then
    echo "ERROR: demo-api traffic endpoint did not become ready through service/${traffic_service}." >&2
    sed -n '1,80p' "${traffic_log}" >&2 || true
    observability_stop_port_forward "${traffic_pid}" "${traffic_log}"
    observability_print_demo_api_runtime_state \
      "${app_namespace}" "${argocd_namespace}" "${application_name}"
    return 1
  fi

  for _ in $(seq 1 "${request_count}"); do
    if ! curl -fsS "http://127.0.0.1:${local_port}/health" >/dev/null; then
      echo "ERROR: demo-api health traffic failed during telemetry warm-up." >&2
      observability_stop_port_forward "${traffic_pid}" "${traffic_log}"
      observability_print_demo_api_runtime_state \
        "${app_namespace}" "${argocd_namespace}" "${application_name}"
      return 1
    fi
    curl -fsS "http://127.0.0.1:${local_port}/ready" >/dev/null || true
  done

  if ! metrics_payload="$(curl -fsS "http://127.0.0.1:${local_port}/metrics")"; then
    echo "ERROR: the deployed demo-api image does not expose a reachable /metrics endpoint." >&2
    observability_stop_port_forward "${traffic_pid}" "${traffic_log}"
    observability_print_demo_api_runtime_state \
      "${app_namespace}" "${argocd_namespace}" "${application_name}"
    return 1
  fi
  observability_stop_port_forward "${traffic_pid}" "${traffic_log}"

  if ! grep -q '^demo_api_http_requests_total{' <<<"${metrics_payload}"; then
    echo "ERROR: the deployed demo-api image does not expose populated HTTP telemetry." >&2
    echo "The neutral feature baseline is only a replay start state. Build and load a fresh local image tag, then redeploy the exact feature revision before acceptance." >&2
    observability_print_demo_api_runtime_state \
      "${app_namespace}" "${argocd_namespace}" "${application_name}"
    return 1
  fi
  if ! grep -q '^demo_api_dependency_checks_total{' <<<"${metrics_payload}"; then
    echo "ERROR: the deployed demo-api image does not expose populated dependency telemetry." >&2
    observability_print_demo_api_runtime_state \
      "${app_namespace}" "${argocd_namespace}" "${application_name}"
    return 1
  fi

  echo "PASS: bounded demo-api HTTP and dependency telemetry generated through service/${traffic_service}"
}

observability_print_prometheus_job_diagnostics() {
  local prometheus_base_url="$1"
  local job_name="$2"
  local payload

  if ! payload="$(curl -fsS "${prometheus_base_url}/api/v1/targets?state=active")"; then
    echo "DIAGNOSTIC: unable to query active Prometheus targets." >&2
    return 0
  fi

  echo "DIAGNOSTIC: Prometheus targets for job=${job_name}:" >&2
  jq -c --arg job "${job_name}" '
    [.data.activeTargets[]
      | select(.labels.job == $job)
      | {
          health,
          scrapeUrl,
          lastError,
          lastScrape
        }
    ]
  ' <<<"${payload}" >&2 || true
}

observability_assert_prometheus_jobs_up() {
  local prometheus_base_url="$1"
  shift
  local job_name
  local expression
  local payload

  for job_name in "$@"; do
    expression="min(up{job=\"${job_name}\"})"
    payload="$(curl -fsS --get "${prometheus_base_url}/api/v1/query" \
      --data-urlencode "query=${expression}")"
    if jq -e '
      .status == "success" and
      (.data.result | length) == 1 and
      (.data.result[0].value[1] | tonumber) >= 1
    ' <<<"${payload}" >/dev/null; then
      echo "PASS: every discovered Prometheus target is up: ${job_name}"
      continue
    fi

    echo "ERROR: Prometheus job is absent or has a target with up=0: ${job_name}" >&2
    observability_print_prometheus_job_diagnostics "${prometheus_base_url}" "${job_name}"
    return 1
  done
}
