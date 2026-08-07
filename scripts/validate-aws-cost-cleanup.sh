#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

if [[ "${AWS_ENVIRONMENT}" == "aws-prod" ]]; then
  echo "This portfolio cleanup audit does not treat aws-prod as disposable." >&2
  exit 1
fi

for command in aws jq terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

failures=()
record_count() {
  local label="$1"
  local count="$2"
  if [[ ! "${count}" =~ ^[0-9]+$ ]]; then
    echo "Unexpected count for ${label}: ${count}" >&2
    exit 1
  fi
  if (( count > 0 )); then
    failures+=("${label}: ${count}")
  fi
}

echo "==> Verifying AWS identity and Terraform state"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[[ "${ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || {
  echo "AWS account identity is invalid." >&2
  exit 1
}

if [[ -d "${TF_DIR}/.terraform" || -f "${TF_DIR}/terraform.tfstate" ]]; then
  STATE_LIST="$(terraform -chdir="${TF_DIR}" state list 2>/dev/null || true)"
  STATE_COUNT="$(sed '/^$/d' <<<"${STATE_LIST}" | wc -l | tr -d ' ')"
  record_count "Terraform state resources" "${STATE_COUNT}"
fi

echo "==> Verifying exact cluster, network, compute, storage, and edge identities"
if aws eks describe-cluster --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null 2>&1; then
  failures+=("EKS cluster still exists: ${CLUSTER_NAME}")
fi

TAG_FILTERS=(
  "Name=tag:Project,Values=${PROJECT_NAME}"
  "Name=tag:Environment,Values=${ENVIRONMENT_SHORT}"
)
record_count "non-terminated EC2 instances" "$(aws ec2 describe-instances \
  --region "${AWS_REGION}" \
  --filters "${TAG_FILTERS[@]}" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'length(Reservations[].Instances[])' --output text)"
record_count "EBS volumes" "$(aws ec2 describe-volumes \
  --region "${AWS_REGION}" --filters "${TAG_FILTERS[@]}" \
  --query 'length(Volumes)' --output text)"
record_count "NAT Gateways" "$(aws ec2 describe-nat-gateways \
  --region "${AWS_REGION}" --filter "${TAG_FILTERS[@]}" \
  --query 'length(NatGateways[?State!=`deleted`])' --output text)"
record_count "Elastic IP allocations" "$(aws ec2 describe-addresses \
  --region "${AWS_REGION}" --filters "${TAG_FILTERS[@]}" \
  --query 'length(Addresses)' --output text)"
record_count "VPCs" "$(aws ec2 describe-vpcs \
  --region "${AWS_REGION}" \
  --filters "Name=tag:Name,Values=${PROJECT_NAME}-${ENVIRONMENT_SHORT}-vpc" \
  --query 'length(Vpcs)' --output text)"

ALB_RESIDUALS="$(aws resourcegroupstaggingapi get-resources \
  --region "${AWS_REGION}" \
  --resource-type-filters \
    elasticloadbalancing:loadbalancer \
    elasticloadbalancing:targetgroup \
  --tag-filters "Key=elbv2.k8s.aws/cluster,Values=${CLUSTER_NAME}" \
  --query 'length(ResourceTagMappingList)' \
  --output text)"
record_count "ALB load balancers or target groups" "${ALB_RESIDUALS}"

BUCKET_NAME="${PROJECT_NAME}-${ENVIRONMENT_SHORT}-${ACCOUNT_ID}-${AWS_REGION}-cnpg"
if aws s3api head-bucket --bucket "${BUCKET_NAME}" >/dev/null 2>&1; then
  failures+=("S3 backup bucket still exists: ${BUCKET_NAME}")
fi

SECRET_NAME="${PROJECT_NAME}-${ENVIRONMENT_SHORT}/demo-api/postgresql"
if secret_json="$(aws secretsmanager describe-secret \
  --region "${AWS_REGION}" --secret-id "${SECRET_NAME}" --output json 2>/dev/null)"; then
  if ! jq --exit-status '.DeletedDate != null' <<<"${secret_json}" >/dev/null; then
    failures+=("Secrets Manager secret is not scheduled for deletion: ${SECRET_NAME}")
  else
    echo "Secrets Manager tombstone is within its configured recovery window."
  fi
fi

record_count "CloudWatch EKS log groups" "$(aws logs describe-log-groups \
  --region "${AWS_REGION}" \
  --log-group-name-prefix "/aws/eks/${CLUSTER_NAME}/cluster" \
  --query "length(logGroups[?logGroupName=='/aws/eks/${CLUSTER_NAME}/cluster'])" \
  --output text)"
record_count "ACM certificates" "$(aws acm list-certificates \
  --region "${AWS_REGION}" \
  --query "length(CertificateSummaryList[?DomainName=='${DEMO_HOSTNAME}'])" \
  --output text)"

ZONE_ID="$(aws route53 list-hosted-zones-by-name \
  --dns-name "${HOSTED_ZONE_NAME}" \
  --query "HostedZones[?Name=='${HOSTED_ZONE_NAME}.'] | [0].Id" \
  --output text | sed 's#^/hostedzone/##')"
if [[ -n "${ZONE_ID}" && "${ZONE_ID}" != "None" ]]; then
  ALIAS_RECORD="$(aws route53 list-resource-record-sets \
    --hosted-zone-id "${ZONE_ID}" \
    --query "ResourceRecordSets[?Name=='${DEMO_HOSTNAME}.' && Type=='A'] | [0]" \
    --output json)"
  if [[ "${ALIAS_RECORD}" != "null" ]]; then
    failures+=("Route 53 A record still exists: ${DEMO_HOSTNAME}")
  fi
fi

echo "==> Sweeping currently tagged regional resources"
TAGGED_JSON="$(aws resourcegroupstaggingapi get-resources \
  --region "${AWS_REGION}" \
  --tag-filters \
    "Key=Project,Values=${PROJECT_NAME}" \
    "Key=Environment,Values=${ENVIRONMENT_SHORT}" \
  --output json)"
TAGGED_ARNS="$(jq -r \
  --arg secret_marker ":secret:${SECRET_NAME}-" '
    [.ResourceTagMappingList[].ResourceARN
      | select(contains($secret_marker) | not)]
    | .[]
  ' <<<"${TAGGED_JSON}")"
if [[ -n "${TAGGED_ARNS}" ]]; then
  failures+=("tagged resources remain")
  printf '%s\n' "${TAGGED_ARNS}" >&2
fi

if (( ${#failures[@]} > 0 )); then
  echo "AWS cleanup audit failed:" >&2
  printf '  - %s\n' "${failures[@]}" >&2
  exit 1
fi

echo "AWS cleanup audit passed for ${AWS_ENVIRONMENT}."
echo "No continuing cluster, network, compute, volume, load-balancer, bucket, certificate, DNS, or tagged-resource identity was found."
