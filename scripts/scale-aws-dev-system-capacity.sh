#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${ROOT_DIR}/infra/terraform/aws/environments/dev"
AWS_REGION="${AWS_REGION:-us-east-1}"
[[ "${CONFIRM_SYSTEM_SCALE:-}" == scale-aws-dev-to-four ]] || {
  echo 'Billable change: set CONFIRM_SYSTEM_SCALE=scale-aws-dev-to-four.' >&2; exit 1;
}
[[ "${EXPECTED_AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] || exit 1
export AWS_REGION
"${ROOT_DIR}/scripts/wait-aws-dev-system-nodes.py" --check-context
[[ "$(aws sts get-caller-identity --query Account --output text)" == "${EXPECTED_AWS_ACCOUNT_ID}" ]] || exit 1
CLUSTER="$(aws eks describe-cluster --region "${AWS_REGION}" --name startup-devops-baseline-dev --output json)"
CIDRS="$(jq -ce '.cluster.resourcesVpcConfig.publicAccessCidrs' <<<"${CLUSTER}")"
LOGS="$(jq -ce '[.cluster.logging.clusterLogging[]? | select(.enabled) | .types[]] | unique' <<<"${CLUSTER}")"
WORK="$(mktemp -d)"
trap 'rm -rf -- "${WORK}"' EXIT
terraform -chdir="${TF_DIR}" init -input=false
terraform -chdir="${TF_DIR}" plan -input=false -out="${WORK}/scale.tfplan" \
  -var="eks_public_access_cidrs=${CIDRS}" -var="eks_enabled_cluster_log_types=${LOGS}"
terraform -chdir="${TF_DIR}" show -json "${WORK}/scale.tfplan" >"${WORK}/plan.json"
python3 - "${WORK}/plan.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
def unknown(value):
    if isinstance(value, dict): return any(unknown(v) for v in value.values())
    if isinstance(value, list): return any(unknown(v) for v in value)
    return value is True
for item in plan.get('resource_changes', []):
    if item.get('mode') == 'data' or item['change']['actions'] == ['no-op']:
        continue
    assert item['address'] == 'module.eks.aws_eks_node_group.general', 'Unrelated resource change: STOP'
    change = item['change']
    assert change['actions'] == ['update'], 'Creation/replacement/deletion forbidden'
    before, after = change['before'].copy(), change['after'].copy()
    old, new = before.pop('scaling_config')[0], after.pop('scaling_config')[0]
    assert new == {'min_size':4, 'max_size':4, 'desired_size':4}, 'Unexpected scaling target'
    assert all(old[k] <= new[k] for k in new), 'Scale-down forbidden'
    assert before == after, 'Non-scaling change forbidden'
    assert not unknown(change.get('after_unknown')), 'Unknown changed values require manual review'
print('Plan restricted to in-place system node group expansion.')
PY
read -r -p 'Apply reviewed billable expansion? Type scale-aws-dev-to-four: ' answer
[[ "${answer}" == scale-aws-dev-to-four ]] || exit 1
terraform -chdir="${TF_DIR}" apply -input=false "${WORK}/scale.tfplan"
echo 'Terraform apply completed. Waiting for four Ready system nodes; do not repeat expansion if this wait fails.'
"${ROOT_DIR}/scripts/wait-aws-dev-system-nodes.py"
