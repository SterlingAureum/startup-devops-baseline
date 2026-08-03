#!/usr/bin/env bash
set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
INGRESS_NAME="${INGRESS_NAME:-demo-api}"
HOSTED_ZONE_NAME="${HOSTED_ZONE_NAME:-aureumstack.com}"
DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.dev.aureumstack.com}"
DNS_ACTION="${DNS_ACTION:-${1:-upsert}}"

for command in aws jq kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "${DNS_ACTION}" != "upsert" && "${DNS_ACTION}" != "delete" ]]; then
  echo "DNS_ACTION must be upsert or delete." >&2
  exit 1
fi

ZONE_JSON="$(
  aws route53 list-hosted-zones-by-name \
    --dns-name "${HOSTED_ZONE_NAME}" \
    --output json
)"
ZONE_ID="$(
  jq -r --arg name "${HOSTED_ZONE_NAME}." '
    [.HostedZones[] | select(.Name == $name and .Config.PrivateZone == false)] |
    if length == 1 then .[0].Id | sub("^/hostedzone/"; "") else empty end
  ' <<<"${ZONE_JSON}"
)"
if [[ -z "${ZONE_ID}" ]]; then
  echo "Exactly one public Route 53 hosted zone for ${HOSTED_ZONE_NAME} is required." >&2
  exit 1
fi

if [[ "${DNS_ACTION}" == "delete" ]]; then
  CURRENT_RECORD="$(
    aws route53 list-resource-record-sets \
      --hosted-zone-id "${ZONE_ID}" \
      --query "ResourceRecordSets[?Name=='${DEMO_HOSTNAME}.' && Type=='A'] | [0]" \
      --output json
  )"
  if [[ "${CURRENT_RECORD}" == "null" ]]; then
    echo "Route 53 Alias ${DEMO_HOSTNAME} is already absent."
    exit 0
  fi
  CHANGE_BATCH="$(
    jq -n --argjson record "${CURRENT_RECORD}" '{Changes: [{Action: "DELETE", ResourceRecordSet: $record}]}'
  )"
else
  aws eks update-kubeconfig \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" >/dev/null

  ALB_HOSTNAME="$(
    kubectl get ingress "${INGRESS_NAME}" \
      --namespace "${APP_NAMESPACE}" \
      --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'
  )"
  if [[ ! "${ALB_HOSTNAME}" =~ \.elb\.amazonaws\.com$ ]]; then
    echo "The Ingress does not expose a valid AWS load balancer hostname." >&2
    exit 1
  fi

  LOAD_BALANCER="$(
    aws elbv2 describe-load-balancers \
      --region "${AWS_REGION}" \
      --output json |
      jq -c --arg dns "${ALB_HOSTNAME}" '
        [.LoadBalancers[] | select(.DNSName == $dns)] |
        if length == 1 then .[0] else empty end
      '
  )"
  if [[ -z "${LOAD_BALANCER}" ]]; then
    echo "Exactly one ALB must match ${ALB_HOSTNAME}." >&2
    exit 1
  fi

  ALB_ZONE_ID="$(jq -r '.CanonicalHostedZoneId' <<<"${LOAD_BALANCER}")"
  ALIAS_DNS_NAME="${ALB_HOSTNAME}"
  if [[ "${ALIAS_DNS_NAME}" != dualstack.* ]]; then
    ALIAS_DNS_NAME="dualstack.${ALIAS_DNS_NAME}"
  fi

  CHANGE_BATCH="$(
    jq -n \
      --arg name "${DEMO_HOSTNAME}" \
      --arg dns_name "${ALIAS_DNS_NAME}" \
      --arg zone_id "${ALB_ZONE_ID}" \
      '{Changes: [{Action: "UPSERT", ResourceRecordSet: {
        Name: $name,
        Type: "A",
        AliasTarget: {
          DNSName: $dns_name,
          HostedZoneId: $zone_id,
          EvaluateTargetHealth: true
        }
      }}]}'
  )"
fi

CHANGE_ID="$(
  aws route53 change-resource-record-sets \
    --hosted-zone-id "${ZONE_ID}" \
    --change-batch "${CHANGE_BATCH}" \
    --query 'ChangeInfo.Id' \
    --output text
)"
aws route53 wait resource-record-sets-changed --id "${CHANGE_ID}"

if [[ "${DNS_ACTION}" == "delete" ]]; then
  echo "Route 53 Alias ${DEMO_HOSTNAME} deletion passed."
else
  echo "Route 53 Alias ${DEMO_HOSTNAME} reconciliation passed."
fi
