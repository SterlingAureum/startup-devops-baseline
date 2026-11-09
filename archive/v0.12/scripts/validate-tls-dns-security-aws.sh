#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
INGRESS_NAME="${INGRESS_NAME:-demo-api}"
EXPECTED_LOG_RETENTION_DAYS="${EXPECTED_LOG_RETENTION_DAYS:-${EKS_CLUSTER_LOG_RETENTION_DAYS}}"
EXPECTED_LOG_TYPES_JSON="${EXPECTED_LOG_TYPES_JSON:-[\"api\",\"audit\",\"authenticator\",\"controllerManager\",\"scheduler\"]}"

for command in aws curl jq kubectl openssl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Validating EKS endpoint access and security logging"
CLUSTER_JSON="$(
  aws eks describe-cluster \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" \
    --output json
)"
if ! jq --exit-status --argjson expected "${EXPECTED_LOG_TYPES_JSON}" '
  .cluster.resourcesVpcConfig.endpointPublicAccess == true and
  .cluster.resourcesVpcConfig.endpointPrivateAccess == true and
  (.cluster.resourcesVpcConfig.publicAccessCidrs | length > 0) and
  (.cluster.resourcesVpcConfig.publicAccessCidrs | index("0.0.0.0/0") | not) and
  ([.cluster.logging.clusterLogging[] |
    select(.enabled == true) | .types[]] | unique | sort) == ($expected | unique | sort)
' <<<"${CLUSTER_JSON}" >/dev/null; then
  echo "EKS endpoint or production-parity logging is not hardened as expected." >&2
  exit 1
fi

LOG_RETENTION="$(
  aws logs describe-log-groups \
    --region "${AWS_REGION}" \
    --log-group-name-prefix "/aws/eks/${CLUSTER_NAME}/cluster" \
    --output json |
    jq -r --arg name "/aws/eks/${CLUSTER_NAME}/cluster" '
      [.logGroups[] | select(.logGroupName == $name)] |
      if length == 1 then .[0].retentionInDays else empty end
    '
)"
if [[ "${LOG_RETENTION}" != "${EXPECTED_LOG_RETENTION_DAYS}" ]]; then
  echo "Unexpected EKS log retention: ${LOG_RETENTION:-missing}" >&2
  exit 1
fi

echo "==> Validating ACM certificate"
CERTIFICATE_ARN="$(
  aws acm list-certificates \
    --region "${AWS_REGION}" \
    --certificate-statuses ISSUED \
    --output json |
    jq -r --arg domain "${DEMO_HOSTNAME}" '
      [.CertificateSummaryList[] | select(.DomainName == $domain)] |
      if length == 1 then .[0].CertificateArn else empty end
    '
)"
if [[ -z "${CERTIFICATE_ARN}" ]]; then
  echo "Exactly one issued ACM certificate for ${DEMO_HOSTNAME} is required." >&2
  exit 1
fi
if ! aws acm describe-certificate \
  --region "${AWS_REGION}" \
  --certificate-arn "${CERTIFICATE_ARN}" \
  --output json |
  jq --exit-status --arg domain "${DEMO_HOSTNAME}" '
    .Certificate.Status == "ISSUED" and
    .Certificate.DomainName == $domain and
    all(.Certificate.DomainValidationOptions[]; .ValidationStatus == "SUCCESS")
  ' >/dev/null; then
  echo "ACM certificate validation is incomplete." >&2
  exit 1
fi

aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Validating HTTPS Ingress and Route 53 Alias"
INGRESS_JSON="$(
  kubectl get ingress "${INGRESS_NAME}" \
    --namespace "${APP_NAMESPACE}" \
    --output json
)"
if ! jq --exit-status --arg host "${DEMO_HOSTNAME}" '
  .spec.rules[0].host == $host and
  .metadata.annotations["alb.ingress.kubernetes.io/ssl-redirect"] == "443" and
  .metadata.annotations["alb.ingress.kubernetes.io/ssl-policy"] == "ELBSecurityPolicy-TLS13-1-2-2021-06" and
  (.metadata.annotations["alb.ingress.kubernetes.io/listen-ports"] | contains("HTTPS"))
' <<<"${INGRESS_JSON}" >/dev/null; then
  echo "The live Ingress does not match the HTTPS contract." >&2
  exit 1
fi
ALB_HOSTNAME="$(jq -r '.status.loadBalancer.ingress[0].hostname // empty' <<<"${INGRESS_JSON}")"
if [[ -z "${ALB_HOSTNAME}" ]]; then
  echo "The Ingress does not have an ALB hostname." >&2
  exit 1
fi

ZONE_ID="$(
  aws route53 list-hosted-zones-by-name \
    --dns-name "${HOSTED_ZONE_NAME}" \
    --output json |
    jq -r --arg name "${HOSTED_ZONE_NAME}." '
      [.HostedZones[] | select(.Name == $name and .Config.PrivateZone == false)] |
      if length == 1 then .[0].Id | sub("^/hostedzone/"; "") else empty end
    '
)"
if [[ -z "${ZONE_ID}" ]]; then
  echo "The public Route 53 hosted zone was not resolved." >&2
  exit 1
fi
ALIAS_TARGET="$(
  aws route53 list-resource-record-sets \
    --hosted-zone-id "${ZONE_ID}" \
    --query "ResourceRecordSets[?Name=='${DEMO_HOSTNAME}.' && Type=='A'] | [0].AliasTarget.DNSName" \
    --output text
)"
if [[ "${ALIAS_TARGET#dualstack.}" != "${ALB_HOSTNAME}." &&
      "${ALIAS_TARGET#dualstack.}" != "${ALB_HOSTNAME}" ]]; then
  echo "Route 53 Alias does not target the live ALB." >&2
  exit 1
fi

echo "==> Validating redirect, TLS identity, and application endpoints"
HEADERS="$(curl --silent --show-error --head --connect-timeout 10 --max-time 30 "http://${DEMO_HOSTNAME}/health")"
HTTP_STATUS="$(awk 'NR == 1 {print $2}' <<<"${HEADERS}")"
LOCATION="$(awk 'BEGIN {IGNORECASE=1} /^location:/ {gsub("\r", "", $2); print $2}' <<<"${HEADERS}")"
if [[ "${HTTP_STATUS}" != "301" || "${LOCATION}" != https://* ]]; then
  echo "HTTP does not redirect to HTTPS with status 301." >&2
  exit 1
fi

openssl s_client \
  -connect "${DEMO_HOSTNAME}:443" \
  -servername "${DEMO_HOSTNAME}" </dev/null 2>/dev/null |
  openssl x509 -noout -checkhost "${DEMO_HOSTNAME}" >/dev/null

for path in health ready version db/health; do
  curl --proto '=https' --tlsv1.2 \
    --fail --silent --show-error \
    --retry 12 --retry-delay 10 \
    "https://${DEMO_HOSTNAME}/${path}" >/dev/null
done

kubectl wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${DEMO_APPLICATION}" \
  --namespace argocd \
  --timeout=10m
kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${DEMO_APPLICATION}" \
  --namespace argocd \
  --timeout=10m

echo "TLS, DNS, EKS endpoint, logging, and HTTPS runtime validation passed."
