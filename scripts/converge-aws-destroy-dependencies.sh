#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

MODE="${1:-}"
DESTROY_VPC_ID="${DESTROY_VPC_ID:-}"
WAIT_SECONDS="${DESTROY_DEPENDENCY_WAIT_SECONDS:-300}"
POLL_SECONDS="${DESTROY_DEPENDENCY_POLL_SECONDS:-10}"

if [[ "${INTERNAL_AWS_DESTROY_DEPENDENCY_TOKEN:-}" != \
      "converge-reviewed-destroy-dependencies" ]]; then
  echo "This helper is internal to the reviewed destroy entrypoint." >&2
  exit 1
fi

case "${AWS_ENVIRONMENT}" in
  aws-dev|aws-test) ;;
  *)
    echo "Destroy dependency convergence accepts only aws-dev or aws-test." >&2
    exit 1
    ;;
esac

case "${MODE}" in
  pre-terraform|post-failure|post-success) ;;
  *)
    echo "Usage: $0 pre-terraform|post-failure|post-success" >&2
    exit 1
    ;;
esac

[[ "${DESTROY_VPC_ID}" =~ ^vpc-[0-9a-f]+$ ]] || {
  echo "DESTROY_VPC_ID must be an exact VPC ID." >&2
  exit 1
}
[[ "${WAIT_SECONDS}" =~ ^[0-9]+$ ]] || {
  echo "DESTROY_DEPENDENCY_WAIT_SECONDS must be a nonnegative integer." >&2
  exit 1
}
[[ "${POLL_SECONDS}" =~ ^[0-9]+$ ]] || {
  echo "DESTROY_DEPENDENCY_POLL_SECONDS must be a nonnegative integer." >&2
  exit 1
}

for command_name in aws jq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

CALLER_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[[ "${CALLER_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || {
  echo "AWS caller account is invalid." >&2
  exit 1
}

wait_for_absence() {
  local resource_type="$1"
  local resource_id="$2"
  local deadline=$((SECONDS + WAIT_SECONDS))
  local lookup_output

  while true; do
    case "${resource_type}" in
      volume)
        if lookup_output="$(aws ec2 describe-volumes \
          --region "${AWS_REGION}" \
          --volume-ids "${resource_id}" \
          --output json 2>&1)"; then
          :
        elif grep -q 'InvalidVolume\.NotFound' <<<"${lookup_output}"; then
          return 0
        else
          printf '%s\n' "${lookup_output}" >&2
          return 1
        fi
        ;;
      network-interface)
        if lookup_output="$(aws ec2 describe-network-interfaces \
          --region "${AWS_REGION}" \
          --network-interface-ids "${resource_id}" \
          --output json 2>&1)"; then
          :
        elif grep -q 'InvalidNetworkInterfaceID\.NotFound' <<<"${lookup_output}"; then
          return 0
        else
          printf '%s\n' "${lookup_output}" >&2
          return 1
        fi
        ;;
      security-group)
        if lookup_output="$(aws ec2 describe-security-groups \
          --region "${AWS_REGION}" \
          --group-ids "${resource_id}" \
          --output json 2>&1)"; then
          :
        elif grep -q 'InvalidGroup\.NotFound' <<<"${lookup_output}"; then
          return 0
        else
          printf '%s\n' "${lookup_output}" >&2
          return 1
        fi
        ;;
      *)
        echo "Unsupported absence wait type: ${resource_type}" >&2
        return 1
        ;;
    esac

    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for ${resource_type} ${resource_id} deletion." >&2
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

delete_safe_dynamic_pvc_volumes() {
  local volume_json volume_id volume_record volume_state attachment_count
  local deadline

  volume_json="$(aws ec2 describe-volumes \
    --region "${AWS_REGION}" \
    --filters \
      "Name=tag:Project,Values=${PROJECT_NAME}" \
      "Name=tag:Environment,Values=${ENVIRONMENT_SHORT}" \
      "Name=tag:kubernetes.io/cluster/${CLUSTER_NAME},Values=owned" \
    --output json)"

  while IFS= read -r volume_id; do
    [[ -n "${volume_id}" ]] || continue
    deadline=$((SECONDS + WAIT_SECONDS))
    while true; do
      if volume_record="$(aws ec2 describe-volumes \
        --region "${AWS_REGION}" \
        --volume-ids "${volume_id}" \
        --output json 2>&1)"; then
        :
      elif grep -q 'InvalidVolume\.NotFound' <<<"${volume_record}"; then
        break
      else
        printf '%s\n' "${volume_record}" >&2
        return 1
      fi

      jq --exit-status \
        --arg id "${volume_id}" \
        --arg project "${PROJECT_NAME}" \
        --arg environment "${ENVIRONMENT_SHORT}" \
        --arg cluster_tag "kubernetes.io/cluster/${CLUSTER_NAME}" \
        --arg name_prefix "${PROJECT_NAME}-${ENVIRONMENT_SHORT}-dynamic-pvc-" '
        def tag_value($key):
          [.Tags[]? | select(.Key == $key) | .Value][0] // null;
        .Volumes
        | map(select(.VolumeId == $id))
        | length == 1 and
          (
            .[0]
            | .Encrypted == true and
              tag_value("Project") == $project and
              tag_value("Environment") == $environment and
              tag_value($cluster_tag) == "owned" and
              (tag_value("Name") | startswith($name_prefix))
          )
      ' <<<"${volume_record}" >/dev/null || {
        echo "Refusing unrecognized residual EBS volume ${volume_id}." >&2
        return 1
      }

      volume_state="$(jq -r '.Volumes[0].State' <<<"${volume_record}")"
      attachment_count="$(jq '.Volumes[0].Attachments | length' <<<"${volume_record}")"
      case "${volume_state}" in
        available)
          [[ "${attachment_count}" == "0" ]] || {
            echo "Refusing available EBS volume ${volume_id} with attachments." >&2
            return 1
          }
          echo "Deleting exact detached dynamic-PVC volume ${volume_id}."
          aws ec2 delete-volume --region "${AWS_REGION}" --volume-id "${volume_id}"
          wait_for_absence volume "${volume_id}"
          break
          ;;
        deleting)
          wait_for_absence volume "${volume_id}"
          break
          ;;
        in-use)
          if (( SECONDS >= deadline )); then
            echo "Timed out waiting for dynamic-PVC volume ${volume_id} to detach." >&2
            return 1
          fi
          sleep "${POLL_SECONDS}"
          ;;
        *)
          echo "Refusing dynamic-PVC volume ${volume_id} in state ${volume_state}." >&2
          return 1
          ;;
      esac
    done
  done < <(jq -r '.Volumes[].VolumeId' <<<"${volume_json}")
}

delete_safe_orphan_kubernetes_enis() {
  local eni_json eni_id eni_record parent_instance_id instance_json instance_state

  eni_json="$(aws ec2 describe-network-interfaces \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"

  while IFS= read -r eni_id; do
    [[ -n "${eni_id}" ]] || continue
    eni_record="$(jq -c \
      --arg id "${eni_id}" \
      '.NetworkInterfaces[] | select(.NetworkInterfaceId == $id)' \
      <<<"${eni_json}")"
    jq --exit-status \
      --arg vpc "${DESTROY_VPC_ID}" '
      .VpcId == $vpc and
      .Status == "available" and
      .RequesterManaged == false and
      .InterfaceType == "interface" and
      (.Attachment == null) and
      (.Description | test("^aws-K8S-i-[0-9a-f]+$"))
    ' <<<"${eni_record}" >/dev/null || {
      echo "Refusing unrecognized Kubernetes ENI ${eni_id}." >&2
      return 1
    }

    parent_instance_id="$(jq -r \
      '.Description | sub("^aws-K8S-"; "")' \
      <<<"${eni_record}")"
    if instance_json="$(aws ec2 describe-instances \
      --region "${AWS_REGION}" \
      --instance-ids "${parent_instance_id}" \
      --output json 2>&1)"; then
      instance_state="$(jq -r \
        '.Reservations[0].Instances[0].State.Name // empty' \
        <<<"${instance_json}")"
      if [[ "${instance_state}" != "terminated" ]]; then
        echo "Refusing ENI ${eni_id}; parent instance is ${instance_state:-unknown}." >&2
        return 1
      fi
    elif ! grep -q 'InvalidInstanceID\.NotFound' <<<"${instance_json}"; then
      printf '%s\n' "${instance_json}" >&2
      return 1
    fi

    echo "Deleting exact detached Kubernetes ENI ${eni_id}."
    aws ec2 delete-network-interface \
      --region "${AWS_REGION}" \
      --network-interface-id "${eni_id}"
    wait_for_absence network-interface "${eni_id}"
  done < <(jq -r '
    .NetworkInterfaces[]
    | select(
        .Status == "available" and
        .RequesterManaged == false and
        .InterfaceType == "interface" and
        (.Attachment == null) and
        (.Description | test("^aws-K8S-i-[0-9a-f]+$"))
      )
    | .NetworkInterfaceId
  ' <<<"${eni_json}")
}

require_cluster_absent() {
  local cluster_output

  if cluster_output="$(aws eks describe-cluster \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" \
    --output json 2>&1)"; then
    echo "Refusing post-Terraform convergence while EKS still exists." >&2
    return 1
  fi
  if ! grep -q 'ResourceNotFoundException' <<<"${cluster_output}"; then
    printf '%s\n' "${cluster_output}" >&2
    return 1
  fi
}

delete_safe_orphan_eks_security_group() {
  local sg_inventory target_count sg_id eni_count reference_count

  sg_inventory="$(aws ec2 describe-security-groups \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  target_count="$(jq \
    --arg prefix "eks-cluster-sg-${CLUSTER_NAME}-" '
    [.SecurityGroups[]
      | select(
          (.GroupName | startswith($prefix)) and
          (.Description | startswith("EKS created security group"))
        )]
    | length
  ' <<<"${sg_inventory}")"
  if (( target_count > 1 )); then
    echo "Refusing multiple EKS-created security-group candidates." >&2
    return 1
  fi
  (( target_count == 1 )) || return 0

  sg_id="$(jq -r \
    --arg prefix "eks-cluster-sg-${CLUSTER_NAME}-" '
    .SecurityGroups[]
    | select(
        (.GroupName | startswith($prefix)) and
        (.Description | startswith("EKS created security group"))
      )
    | .GroupId
  ' <<<"${sg_inventory}")"

  jq --exit-status \
    --arg id "${sg_id}" \
    --arg vpc "${DESTROY_VPC_ID}" \
    --arg owner "${CALLER_ACCOUNT_ID}" \
    --arg prefix "eks-cluster-sg-${CLUSTER_NAME}-" '
    .SecurityGroups
    | map(select(.GroupId == $id))
    | length == 1 and
      (
        .[0]
        | .VpcId == $vpc and
          .OwnerId == $owner and
          .GroupName != "default" and
          (.GroupName | startswith($prefix)) and
          (.Description | startswith("EKS created security group"))
      )
  ' <<<"${sg_inventory}" >/dev/null || {
    echo "Refusing unrecognized EKS security group ${sg_id}." >&2
    return 1
  }

  eni_count="$(aws ec2 describe-network-interfaces \
    --region "${AWS_REGION}" \
    --filters "Name=group-id,Values=${sg_id}" \
    --query 'length(NetworkInterfaces)' \
    --output text)"
  [[ "${eni_count}" == "0" ]] || {
    echo "Refusing EKS security group ${sg_id}; ENIs still reference it." >&2
    return 1
  }

  reference_count="$(jq \
    --arg id "${sg_id}" '
    [.SecurityGroups[]
      | (.IpPermissions[]?, .IpPermissionsEgress[]?)
      | .UserIdGroupPairs[]?
      | select(.GroupId == $id)]
    | length
  ' <<<"${sg_inventory}")"
  [[ "${reference_count}" == "0" ]] || {
    echo "Refusing EKS security group ${sg_id}; another rule references it." >&2
    return 1
  }

  echo "Deleting exact unreferenced EKS-created security group ${sg_id}."
  aws ec2 delete-security-group --region "${AWS_REGION}" --group-id "${sg_id}"
  wait_for_absence security-group "${sg_id}"
}

assert_only_terraform_owned_vpc_dependencies_remain() {
  local eni_count instance_count nat_count endpoint_count load_balancer_count
  local target_group_count nondefault_sg_count igw_count custom_acl_count
  local nonmain_route_table_count inventory_json

  inventory_json="$(aws ec2 describe-network-interfaces \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  eni_count="$(jq '.NetworkInterfaces | length' <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-instances \
    --region "${AWS_REGION}" \
    --filters \
      "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
      "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
    --output json)"
  instance_count="$(jq '[.Reservations[].Instances[]] | length' <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-nat-gateways \
    --region "${AWS_REGION}" \
    --filter "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  nat_count="$(jq '[.NatGateways[] | select(.State != "deleted")] | length' \
    <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-vpc-endpoints \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  endpoint_count="$(jq '.VpcEndpoints | length' <<<"${inventory_json}")"
  inventory_json="$(aws elbv2 describe-load-balancers \
    --region "${AWS_REGION}" --output json)"
  load_balancer_count="$(jq \
    --arg vpc "${DESTROY_VPC_ID}" \
    '[.LoadBalancers[] | select(.VpcId == $vpc)] | length' \
    <<<"${inventory_json}")"
  inventory_json="$(aws elbv2 describe-target-groups \
    --region "${AWS_REGION}" --output json)"
  target_group_count="$(jq \
    --arg vpc "${DESTROY_VPC_ID}" \
    '[.TargetGroups[] | select(.VpcId == $vpc)] | length' \
    <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-security-groups \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  nondefault_sg_count="$(jq \
    '[.SecurityGroups[] | select(.GroupName != "default")] | length' \
    <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-internet-gateways \
    --region "${AWS_REGION}" \
    --filters "Name=attachment.vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  igw_count="$(jq '.InternetGateways | length' <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-network-acls \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  custom_acl_count="$(jq \
    '[.NetworkAcls[] | select(.IsDefault == false)] | length' \
    <<<"${inventory_json}")"
  inventory_json="$(aws ec2 describe-route-tables \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${DESTROY_VPC_ID}" \
    --output json)"
  nonmain_route_table_count="$(jq '
    [.RouteTables[]
      | select(any(.Associations[]?; .Main == true) | not)]
    | length
  ' <<<"${inventory_json}")"

  jq -n \
    --argjson enis "${eni_count}" \
    --argjson instances "${instance_count}" \
    --argjson natGateways "${nat_count}" \
    --argjson vpcEndpoints "${endpoint_count}" \
    --argjson loadBalancers "${load_balancer_count}" \
    --argjson targetGroups "${target_group_count}" \
    --argjson nondefaultSecurityGroups "${nondefault_sg_count}" \
    --argjson internetGateways "${igw_count}" \
    --argjson customNetworkAcls "${custom_acl_count}" \
    --argjson nonmainRouteTables "${nonmain_route_table_count}" \
    '{
      enis: $enis,
      instances: $instances,
      natGateways: $natGateways,
      vpcEndpoints: $vpcEndpoints,
      loadBalancers: $loadBalancers,
      targetGroups: $targetGroups,
      nondefaultSecurityGroups: $nondefaultSecurityGroups,
      internetGateways: $internetGateways,
      customNetworkAcls: $customNetworkAcls,
      nonmainRouteTables: $nonmainRouteTables
    }'

  for count in \
    "${eni_count}" \
    "${instance_count}" \
    "${nat_count}" \
    "${endpoint_count}" \
    "${load_balancer_count}" \
    "${target_group_count}" \
    "${nondefault_sg_count}" \
    "${igw_count}" \
    "${custom_acl_count}" \
    "${nonmain_route_table_count}"; do
    [[ "${count}" =~ ^[0-9]+$ ]] || {
      echo "Invalid VPC dependency count: ${count}" >&2
      return 1
    }
    (( count == 0 )) || {
      echo "Unknown or live VPC dependencies remain; refusing Terraform retry." >&2
      return 1
    }
  done
}

delete_safe_dynamic_pvc_volumes
delete_safe_orphan_kubernetes_enis

if [[ "${MODE}" == "post-failure" || "${MODE}" == "post-success" ]]; then
  require_cluster_absent
  delete_safe_orphan_eks_security_group
fi

if [[ "${MODE}" == "post-failure" ]]; then
  assert_only_terraform_owned_vpc_dependencies_remain
fi

echo "${AWS_ENVIRONMENT} ${MODE} destroy dependency convergence passed."
