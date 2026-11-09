#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.4.3-aws-environment-teardown-convergence.json"
HELPER="${ROOT_DIR}/scripts/converge-aws-destroy-dependencies.sh"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

for command_name in bash jq python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.6.4.3"
assert contract["version"] == "v0.11.9.3.6.4.3"
assert contract["predecessor"] == "v0.11.9.3.6.4.2"
assert contract["status"] == "aws-environment-teardown-convergence-repaired"
assert contract["implementationBaselineCommit"] == (
    "bca8168004b0cce81c532519c5a301ea9ce4bf16"
)
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == (
    "v0.11.9.3.6.5-aws-dev-runtime-qualification"
)

observation = contract["liveObservation"]
assert observation["environment"] == "aws-dev"
assert observation["timeWindowScopedApproval"] is True
assert observation["initialTerraformStateAddressCount"] == 103
assert observation["terraformPromptTransportAttempt"] == {
    "executorExit": 1,
    "terraformStateAddressCount": 103,
    "terraformMutationStarted": False,
    "privateLogSha256": (
        "9485a5cbc5973ff3f11cda81b16a2d426267ad6fadb0da0ab6a316243b392537"
    ),
}
assert observation["subnetDependencyFailure"]["terraformStateAddressCount"] == 2
assert observation["subnetDependencyFailure"]["dependencyClass"] == (
    "detached-unmanaged-aws-k8s-eni"
)
assert observation["vpcDependencyFailure"]["terraformStateAddressCount"] == 1
assert observation["vpcDependencyFailure"]["dependencyClass"] == (
    "unreferenced-eks-created-security-group"
)
assert observation["postTerraformAuditFailure"] == {
    "terraformStateAddressCount": 0,
    "dependencyClass": "detached-dynamic-pvc-ebs-volumes",
    "residualCount": 2,
}
assert observation["closure"] == {
    "terraformStateAddressCount": 0,
    "cleanupAuditExit": 0,
    "terminalFleetRecordsAccepted": 4,
    "continuingBillableResourceIdentityFound": False,
}

for failure in (
    observation["terraformPromptTransportAttempt"],
    observation["subnetDependencyFailure"],
    observation["vpcDependencyFailure"],
):
    assert re.fullmatch(r"[0-9a-f]{64}", failure["privateLogSha256"])

repair = contract["repair"]
assert repair["sharedImplementation"] == "scripts/destroy-aws-dev.sh"
assert repair["awsTestWrapper"] == "scripts/destroy-aws-test.sh"
assert repair["dependencyHelper"] == (
    "scripts/converge-aws-destroy-dependencies.sh"
)
for key in (
    "allEbsBackedPvcsCapturedBeforePruning",
    "rootAndChildPruningWaited",
    "detachedDynamicPvcVolumeGuardedCleanup",
    "detachedAwsK8sEniGuardedCleanup",
    "unreferencedEksSecurityGroupGuardedCleanup",
    "vpcDependencyInventoryBeforeRetry",
    "terraformRetryRequiresNewInteractivePlanConfirmation",
    "unknownDependencyFailsClosed",
    "awsProdRefused",
):
    assert repair[key] is True
assert repair["repairLiveValidated"] is False
assert all(value is False for value in contract["packageProducer"].values())
boundary = contract["evidenceBoundary"]
assert boundary["rawLogsStoredOutsideRepository"] is True
assert all(
    boundary[key] is False
    for key in (
        "awsAccountCommitted",
        "resourceIdsCommitted",
        "cidrsCommitted",
        "terraformStateCommitted",
        "kubeconfigCommitted",
        "secretDataCommitted",
    )
)

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert not re.search(r"\b(?:eni|sg|subnet|vpc|vol)-[0-9a-f]+\b", serialized)

destroy = (root / "scripts/destroy-aws-dev.sh").read_text()
for marker in (
    "EBS_PVC_RECORDS",
    'select(.spec.csi.driver == "ebs.csi.aws.com")',
    "Deleting the Root Application and waiting for child pruning",
    "Deleting every captured EBS-backed PVC",
    "run_dependency_convergence pre-terraform",
    "run_dependency_convergence post-failure",
    "run_dependency_convergence post-success",
    "assert_retry_state_is_vpc_only",
    "Review the new Terraform plan and confirm again",
):
    assert marker in destroy, marker
assert "-auto-approve" not in destroy

helper = (root / "scripts/converge-aws-destroy-dependencies.sh").read_text()
for marker in (
    "pre-terraform|post-failure|post-success",
    "This helper is internal to the reviewed destroy entrypoint",
    "Deleting exact detached dynamic-PVC volume",
    "Deleting exact detached Kubernetes ENI",
    "parent instance is",
    "Deleting exact unreferenced EKS-created security group",
    "Unknown or live VPC dependencies remain",
    "Refusing post-Terraform convergence while EKS still exists",
):
    assert marker in helper, marker

wrapper = (root / "scripts/destroy-aws-test.sh").read_text()
assert 'AWS_ENVIRONMENT="aws-test" exec' in wrapper

for relative, marker in (
    ("README.md", "v0.11.9.3.6.4.3-aws-environment-teardown-convergence"),
    ("CHANGELOG.md", "## v0.11.9.3.6.4.3"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.4.3"),
    (
        "docs/AWS_EKS_DESTROY_RUNBOOK.md",
        "every cluster EBS-backed PVC",
    ),
    (
        "docs/V0.11.9.3.6.4.3_AWS_ENVIRONMENT_TEARDOWN_CONVERGENCE.md",
        "new path has already completed another live teardown",
    ),
    (
        "scripts/validate-ci-quality-gates.sh",
        "validate-v0.11.9.3.6.4.3-aws-environment-teardown-convergence.sh",
    ),
    (
        ".github/CODEOWNERS",
        "/scripts/converge-aws-destroy-dependencies.sh",
    ),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.4.3 teardown evidence and fail-closed design contracts passed.")
PY

mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail

service="${1:-}"
operation="${2:-}"
shift 2 || true
printf '%s %s:%s %s\n' \
  "${AWS_ENVIRONMENT:-unset}" \
  "${service}" \
  "${operation}" \
  "$*" >>"${MOCK_CALL_LOG}"

has_arg() {
  local expected="$1"
  shift
  local argument
  for argument in "$@"; do
    [[ "${argument}" == "${expected}" ]] && return 0
  done
  return 1
}

case "${service}:${operation}" in
  sts:get-caller-identity)
    echo '123456789012'
    ;;
  eks:describe-cluster)
    echo 'An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation' >&2
    exit 254
    ;;
  ec2:describe-volumes)
    if has_arg '--volume-ids' "$@"; then
      if [[ -f "${MOCK_STATE_DIR}/volume-deleted" ]]; then
        echo 'An error occurred (InvalidVolume.NotFound) when calling the DescribeVolumes operation' >&2
        exit 254
      fi
    fi
    if [[ "${MOCK_SCENARIO}" == 'safe' && ! -f "${MOCK_STATE_DIR}/volume-deleted" ]]; then
      printf '{"Volumes":[{"VolumeId":"vol-abc123","State":"available","Encrypted":true,"Attachments":[],"Tags":[{"Key":"Project","Value":"startup-devops-baseline"},{"Key":"Environment","Value":"%s"},{"Key":"kubernetes.io/cluster/%s","Value":"owned"},{"Key":"Name","Value":"startup-devops-baseline-%s-dynamic-pvc-fixture"}]}]}\n' \
        "${ENVIRONMENT_SHORT}" "${CLUSTER_NAME}" "${ENVIRONMENT_SHORT}"
    else
      echo '{"Volumes":[]}'
    fi
    ;;
  ec2:delete-volume)
    touch "${MOCK_STATE_DIR}/volume-deleted"
    ;;
  ec2:describe-network-interfaces)
    if has_arg '--query' "$@"; then
      if [[ "${MOCK_SCENARIO}" == 'unknown' ]]; then echo '1'; else echo '0'; fi
    elif has_arg '--network-interface-ids' "$@" && \
         [[ -f "${MOCK_STATE_DIR}/eni-deleted" ]]; then
      echo 'An error occurred (InvalidNetworkInterfaceID.NotFound) when calling the DescribeNetworkInterfaces operation' >&2
      exit 254
    elif has_arg '--network-interface-ids' "$@" || \
         [[ "${MOCK_SCENARIO}" == 'safe' && ! -f "${MOCK_STATE_DIR}/eni-deleted" ]]; then
      echo '{"NetworkInterfaces":[{"NetworkInterfaceId":"eni-abc123","VpcId":"vpc-abc123","Status":"available","RequesterManaged":false,"InterfaceType":"interface","Attachment":null,"Description":"aws-K8S-i-abc123"}]}'
    elif [[ "${MOCK_SCENARIO}" == 'unknown' ]]; then
      echo '{"NetworkInterfaces":[{"NetworkInterfaceId":"eni-unknown","VpcId":"vpc-abc123","Status":"available","RequesterManaged":false,"InterfaceType":"interface","Attachment":null,"Description":"manual-interface"}]}'
    else
      echo '{"NetworkInterfaces":[]}'
    fi
    ;;
  ec2:delete-network-interface)
    touch "${MOCK_STATE_DIR}/eni-deleted"
    ;;
  ec2:describe-instances)
    if has_arg '--instance-ids' "$@"; then
      echo 'An error occurred (InvalidInstanceID.NotFound) when calling the DescribeInstances operation' >&2
      exit 254
    fi
    echo '{"Reservations":[]}'
    ;;
  ec2:describe-security-groups)
    if has_arg '--query' "$@"; then
      echo '0'
    elif has_arg '--group-ids' "$@" && [[ -f "${MOCK_STATE_DIR}/sg-deleted" ]]; then
      echo 'An error occurred (InvalidGroup.NotFound) when calling the DescribeSecurityGroups operation' >&2
      exit 254
    elif [[ "${MOCK_SCENARIO}" == 'safe' && ! -f "${MOCK_STATE_DIR}/sg-deleted" ]]; then
      printf '{"SecurityGroups":[{"GroupId":"sg-default","VpcId":"vpc-abc123","OwnerId":"123456789012","GroupName":"default","Description":"default VPC security group","IpPermissions":[],"IpPermissionsEgress":[]},{"GroupId":"sg-abc123","VpcId":"vpc-abc123","OwnerId":"123456789012","GroupName":"eks-cluster-sg-%s-fixture","Description":"EKS created security group applied to control plane ENIs","IpPermissions":[],"IpPermissionsEgress":[]}]}\n' \
        "${CLUSTER_NAME}"
    else
      echo '{"SecurityGroups":[{"GroupId":"sg-default","VpcId":"vpc-abc123","OwnerId":"123456789012","GroupName":"default","Description":"default VPC security group","IpPermissions":[],"IpPermissionsEgress":[]}]}'
    fi
    ;;
  ec2:delete-security-group)
    touch "${MOCK_STATE_DIR}/sg-deleted"
    ;;
  ec2:describe-nat-gateways) echo '{"NatGateways":[]}' ;;
  ec2:describe-vpc-endpoints) echo '{"VpcEndpoints":[]}' ;;
  ec2:describe-internet-gateways) echo '{"InternetGateways":[]}' ;;
  ec2:describe-network-acls)
    echo '{"NetworkAcls":[{"IsDefault":true,"Associations":[]}]}'
    ;;
  ec2:describe-route-tables)
    echo '{"RouteTables":[{"Associations":[{"Main":true}]}]}'
    ;;
  elbv2:describe-load-balancers) echo '{"LoadBalancers":[]}' ;;
  elbv2:describe-target-groups) echo '{"TargetGroups":[]}' ;;
  resourcegroupstaggingapi:get-resources)
    echo '{"ResourceTagMappingList":[]}'
    ;;
  *)
    echo "Unexpected fake AWS call: ${service}:${operation} $*" >&2
    exit 1
    ;;
esac
MOCK
chmod +x "${WORK_DIR}/bin/aws"

cat >"${WORK_DIR}/bin/terraform" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"${MOCK_TERRAFORM_CALL_LOG}"
case "$*" in
  *'output -raw vpc_id'*)
    echo 'vpc-abc123'
    ;;
  *'state list'*)
    echo 'module.vpc.aws_vpc.this'
    ;;
  *'destroy'*)
    attempt_file="${MOCK_TERRAFORM_STATE_DIR}/destroy-attempts"
    attempt=0
    [[ ! -f "${attempt_file}" ]] || attempt="$(<"${attempt_file}")"
    attempt=$((attempt + 1))
    printf '%s\n' "${attempt}" >"${attempt_file}"
    if (( attempt == 1 )); then
      echo 'Mock dependency violation.' >&2
      exit 1
    fi
    echo 'Mock Terraform destroy completed.'
    ;;
  *)
    echo "Unexpected fake Terraform call: $*" >&2
    exit 1
    ;;
esac
MOCK

cat >"${WORK_DIR}/bin/kubectl" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "kubectl must not run for cluster-absent retry fixture: $*" >&2
exit 1
MOCK
chmod +x "${WORK_DIR}/bin/terraform" "${WORK_DIR}/bin/kubectl"

run_safe_case() {
  local environment="$1"
  local state_dir="${WORK_DIR}/state-${environment}"
  local call_log="${WORK_DIR}/${environment}.calls"
  local output_file="${WORK_DIR}/${environment}.output"
  mkdir -p "${state_dir}"
  : >"${call_log}"

  PATH="${WORK_DIR}/bin:${PATH}" \
  AWS_ENVIRONMENT="${environment}" \
  DESTROY_VPC_ID='vpc-abc123' \
  DESTROY_DEPENDENCY_WAIT_SECONDS=1 \
  DESTROY_DEPENDENCY_POLL_SECONDS=0 \
  INTERNAL_AWS_DESTROY_DEPENDENCY_TOKEN='converge-reviewed-destroy-dependencies' \
  MOCK_CALL_LOG="${call_log}" \
  MOCK_SCENARIO='safe' \
  MOCK_STATE_DIR="${state_dir}" \
    "${HELPER}" post-failure >"${output_file}"

  for marker in \
    'delete-volume' \
    'delete-network-interface' \
    'delete-security-group'; do
    grep -q "${marker}" "${call_log}" || {
      echo "${environment} safe fixture missed ${marker}." >&2
      exit 1
    }
  done
  grep -q "${environment} post-failure destroy dependency convergence passed" \
    "${output_file}"
}

run_safe_case aws-dev
run_safe_case aws-test

RETRY_STATE_DIR="${WORK_DIR}/state-retry"
RETRY_CALL_LOG="${WORK_DIR}/retry-aws.calls"
RETRY_TERRAFORM_LOG="${WORK_DIR}/retry-terraform.calls"
RETRY_OUTPUT="${WORK_DIR}/retry.output"
mkdir -p "${RETRY_STATE_DIR}" "${WORK_DIR}/tf"
: >"${RETRY_CALL_LOG}"
: >"${RETRY_TERRAFORM_LOG}"
PATH="${WORK_DIR}/bin:${PATH}" \
AWS_ENVIRONMENT='aws-test' \
TF_DIR="${WORK_DIR}/tf" \
CONFIRM_AWS_ENVIRONMENT_DESTROY='destroy-aws-test-with-backups' \
DESTROY_DEPENDENCY_WAIT_SECONDS=1 \
DESTROY_DEPENDENCY_POLL_SECONDS=0 \
MOCK_CALL_LOG="${RETRY_CALL_LOG}" \
MOCK_SCENARIO='safe' \
MOCK_STATE_DIR="${RETRY_STATE_DIR}" \
MOCK_TERRAFORM_CALL_LOG="${RETRY_TERRAFORM_LOG}" \
MOCK_TERRAFORM_STATE_DIR="${RETRY_STATE_DIR}" \
  "${ROOT_DIR}/scripts/destroy-aws-dev.sh" >"${RETRY_OUTPUT}" 2>&1

[[ "$(grep -c 'destroy' "${RETRY_TERRAFORM_LOG}")" == '2' ]] || {
  echo "Terraform retry fixture did not run exactly two destroy attempts." >&2
  exit 1
}
for marker in \
  'Terraform destroy exited 1' \
  'Known dynamic dependencies converged' \
  'Mock Terraform destroy completed' \
  'aws-test destroy completed'; do
  grep -q "${marker}" "${RETRY_OUTPUT}" || {
    echo "Terraform retry fixture missed ${marker}." >&2
    exit 1
  }
done

UNKNOWN_STATE_DIR="${WORK_DIR}/state-unknown"
UNKNOWN_CALL_LOG="${WORK_DIR}/unknown.calls"
mkdir -p "${UNKNOWN_STATE_DIR}"
: >"${UNKNOWN_CALL_LOG}"
if PATH="${WORK_DIR}/bin:${PATH}" \
   AWS_ENVIRONMENT='aws-dev' \
   DESTROY_VPC_ID='vpc-abc123' \
   DESTROY_DEPENDENCY_WAIT_SECONDS=1 \
   DESTROY_DEPENDENCY_POLL_SECONDS=0 \
   INTERNAL_AWS_DESTROY_DEPENDENCY_TOKEN='converge-reviewed-destroy-dependencies' \
   MOCK_CALL_LOG="${UNKNOWN_CALL_LOG}" \
   MOCK_SCENARIO='unknown' \
   MOCK_STATE_DIR="${UNKNOWN_STATE_DIR}" \
     "${HELPER}" post-failure >/dev/null 2>&1; then
  echo "Unknown VPC dependency fixture was accepted." >&2
  exit 1
fi
if grep -Eq 'delete-(volume|network-interface|security-group)' \
  "${UNKNOWN_CALL_LOG}"; then
  echo "Unknown VPC dependency fixture triggered a deletion." >&2
  exit 1
fi

: >"${UNKNOWN_CALL_LOG}"
if PATH="${WORK_DIR}/bin:${PATH}" \
   AWS_ENVIRONMENT='aws-prod' \
   DESTROY_VPC_ID='vpc-abc123' \
   INTERNAL_AWS_DESTROY_DEPENDENCY_TOKEN='converge-reviewed-destroy-dependencies' \
   MOCK_CALL_LOG="${UNKNOWN_CALL_LOG}" \
   MOCK_SCENARIO='safe' \
   MOCK_STATE_DIR="${UNKNOWN_STATE_DIR}" \
     "${HELPER}" post-failure >/dev/null 2>&1; then
  echo "aws-prod dependency convergence was accepted." >&2
  exit 1
fi
[[ ! -s "${UNKNOWN_CALL_LOG}" ]] || {
  echo "aws-prod refusal occurred after an AWS call." >&2
  exit 1
}

bash "${PREDECESSOR}"

bash -n \
  "${ROOT_DIR}/scripts/converge-aws-destroy-dependencies.sh" \
  "${ROOT_DIR}/scripts/destroy-aws-dev.sh" \
  "${ROOT_DIR}/scripts/destroy-aws-test.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.3-aws-environment-teardown-convergence.sh"

if command -v shellcheck >/dev/null 2>&1; then
  (
    cd "${ROOT_DIR}"
    shellcheck -x \
      scripts/converge-aws-destroy-dependencies.sh \
      scripts/destroy-aws-dev.sh \
      scripts/destroy-aws-test.sh \
      scripts/validate-v0.11.9.3.6.4.3-aws-environment-teardown-convergence.sh
  )
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.4.3 dev/test teardown convergence passed; no live operation was executed."
