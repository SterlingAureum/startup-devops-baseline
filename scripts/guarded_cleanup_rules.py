"""Pure dependency and captured ENI/SG rules for future reviewed adapters.

Inputs are complete, freshly parsed observations and reviewed private scope.
Decisions confer no permission and perform no IO, journal writes or mutation.
"""
from __future__ import annotations
import re
from guarded_runtime_rules import RuleViolation, require


CLEANUP_STEPS = (
    'freeze-applications', 'drain-external-secrets', 'delete-business-namespaces',
    'drain-runtime', 'delete-node-config', 'eks-delete', 'eni-sg-cleanup', 'final-delete',
)


def count(observation: dict, key: str) -> int:
    value = observation.get(key)
    require(type(value) is int and value >= 0, 'cleanup-count-schema')
    return value


def truth(observation: dict, key: str) -> None:
    require(observation.get(key) is True, 'cleanup-prerequisite')


def validate_cleanup_step(completed: tuple[str, ...], proposed: str, observation: dict) -> str:
    """Require the next dependency-ordered step and its fresh native conditions.

    Completed steps are confirmed receipts supplied by an adapter, not attempted
    operations. No jump, repeat or forced finalizer path exists. Drain steps may
    wait for controllers; they do not authorize a controller repair or credential
    read. Every stage still needs its own current scope/window/approval checks.
    """
    require(isinstance(completed, tuple) and all(isinstance(s, str) for s in completed), 'cleanup-receipt-schema')
    require(completed == CLEANUP_STEPS[:len(completed)] and len(completed) < len(CLEANUP_STEPS),
            'cleanup-receipt-order')
    require(proposed == CLEANUP_STEPS[len(completed)], 'cleanup-step-order')
    require(isinstance(observation, dict), 'cleanup-observation-schema')
    truth(observation, 'scope_verified'); truth(observation, 'inventory_complete')
    if proposed != 'freeze-applications':
        truth(observation, 'applications_frozen')
        require(count(observation, 'active_application_operations') == 0, 'application-operation-active')
        require(count(observation, 'applications') == 0, 'application-reconciliation-remains')
    if proposed in ('drain-external-secrets', 'delete-business-namespaces'):
        require(count(observation, 'unknown_finalizers') == 0, 'unknown-finalizer-stop')
        if proposed == 'drain-external-secrets' and count(observation, 'external_secrets') > 0:
            truth(observation, 'eso_ready'); truth(observation, 'eso_can_patch')
            truth(observation, 'scoped_rbac_retained')
            require(observation.get('business_namespace_deletion_requested') is False,
                    'namespace-deletion-before-eso-drain')
        if proposed == 'delete-business-namespaces':
            require(count(observation, 'external_secrets') == 0, 'external-secret-drain-incomplete')
    if proposed in ('drain-runtime', 'delete-node-config', 'eks-delete'):
        require(count(observation, 'business_namespaces') == 0, 'business-namespace-remains')
        if proposed == 'drain-runtime':
            truth(observation, 'cleanup_controllers_ready')
        else:
            require(all(count(observation, k) == 0 for k in ('nodeclaims', 'persistent_volumes',
                    'captured_runtime_compute', 'captured_pv_volumes', 'load_balancers', 'target_groups', 'test_dns_records')),
                    'runtime-drain-incomplete')
        if proposed == 'eks-delete':
            require(count(observation, 'nodepools') == count(observation, 'nodeclasses') == 0,
                    'node-config-remains')
    if proposed in ('eni-sg-cleanup', 'final-delete'):
        for key in ('eks_absent', 'captured_compute_absent', 'captured_volumes_absent',
                    'load_balancers_absent', 'target_groups_absent', 'test_dns_absent'):
            truth(observation, key)
        if proposed == 'final-delete':
            truth(observation, 'captured_eni_absent'); truth(observation, 'captured_sg_absent')
    return proposed


def _scope(scope: dict) -> None:
    require(isinstance(scope, dict), 'captured-scope-schema')
    target = scope.get('environment')
    require(target in ('aws-dev', 'aws-test', 'aws-prod'), 'explicit-cleanup-environment')
    for key, pattern in (('account', '[0-9]{12}'), ('vpc_id', 'vpc-[0-9a-f]+'),
                         ('group_id', 'sg-[0-9a-f]+'), ('cluster', '[A-Za-z0-9][A-Za-z0-9_-]*')):
        require(isinstance(scope.get(key), str) and re.fullmatch(pattern, scope[key]), 'captured-scope-identity')
    require(scope['cluster'].endswith('-'+target.removeprefix('aws-')), 'captured-cluster-environment')
    for key, pattern in (('subnet_ids', 'subnet-[0-9a-f]+'), ('instance_ids', 'i-[0-9a-f]+')):
        values = scope.get(key)
        require(isinstance(values, tuple) and bool(values) and all(isinstance(v, str) and re.fullmatch(pattern, v) for v in values),
                'captured-network-or-compute-schema')
        require(len(values) == len(set(values)), 'duplicate-captured-scope')
    for key in ('native_inventory_complete', 'eks_absent', 'captured_compute_absent',
                'captured_volumes_absent', 'load_balancers_absent', 'target_groups_absent', 'test_dns_absent'):
        truth(scope, key)


def _group_ids(row: dict) -> tuple[str, ...]:
    groups = row.get('Groups')
    require(isinstance(groups, list) and bool(groups), 'interface-group-list')
    ids = []
    for group in groups:
        require(isinstance(group, dict) and isinstance(group.get('GroupId'), str)
                and re.fullmatch('sg-[0-9a-f]+', group['GroupId']), 'interface-group-schema')
        ids.append(group['GroupId'])
    require(len(ids) == len(set(ids)), 'duplicate-interface-group')
    return tuple(sorted(ids))


def _eni_identity(row: dict, scope: dict) -> dict:
    require(isinstance(row, dict) and isinstance(row.get('NetworkInterfaceId'), str)
            and re.fullmatch('eni-[0-9a-f]+', row['NetworkInterfaceId']), 'interface-identity')
    require(row.get('OwnerId') == scope['account'] and row.get('VpcId') == scope['vpc_id']
            and row.get('SubnetId') in scope['subnet_ids'], 'interface-owner-or-network')
    require(row.get('InterfaceType') == 'interface' and row.get('RequesterManaged') is False,
            'interface-type-or-requester-managed')
    require(_group_ids(row) == (scope['group_id'],), 'interface-other-group')
    description = row.get('Description')
    require(isinstance(description, str) and description.startswith('aws-K8S'), 'interface-description')
    nodes = re.findall(r'(?<![A-Za-z0-9])i-[0-9a-f]+(?![A-Za-z0-9])', description)
    require(len(nodes) == 1 and nodes[0] in scope['instance_ids'], 'interface-captured-node')
    require('RequesterId' not in row or isinstance(row['RequesterId'], str), 'interface-requester-schema')
    keys = ('NetworkInterfaceId', 'OwnerId', 'VpcId', 'SubnetId', 'Description',
            'InterfaceType', 'RequesterManaged', 'RequesterId')
    return {k: row.get(k) for k in keys} | {'group_ids': _group_ids(row)}


def _safe_eni(row: dict, scope: dict) -> dict:
    identity = _eni_identity(row, scope)
    require(row.get('Status') == 'available' and row.get('Attachment') is None
            and row.get('Association') is None, 'interface-attached-or-associated')
    return identity


def eni_decision(captured: dict, current: dict | None, by_group: list[dict],
                 scope: dict, *, attempted: bool, group_present: bool) -> str:
    """Return delete-once or confirmed-absent; never repeat a prior attempt.

    None must mean a completed native exact-ID absence query, not a missing log.
    The adapter also provides the complete exact-SG interface list and refreshed
    SG existence check. Absent objects skip deletion but do not renew an approval.
    """
    _scope(scope)
    require(type(attempted) is bool and type(group_present) is bool and isinstance(by_group, list),
            'interface-observation-schema')
    expected = _safe_eni(captured, scope)
    if current is None:
        require(by_group == [], 'unexpected-group-interface')
        return 'confirmed-absent'
    require(group_present and len(by_group) == 1 and by_group[0] == current, 'interface-query-disagreement')
    require(_safe_eni(current, scope) == expected, 'captured-interface-drift')
    require(not attempted, 'interface-attempt-already-consumed')
    return 'delete-once'


def _group_identity(group: dict, scope: dict) -> None:
    require(isinstance(group, dict) and group.get('GroupId') == scope['group_id']
            and group.get('OwnerId') == scope['account'] and group.get('VpcId') == scope['vpc_id'],
            'group-owner-or-network')
    name = group.get('GroupName')
    require(isinstance(name, str) and name.startswith('eks-cluster-sg-'+scope['cluster']+'-'), 'group-cluster-ownership')
    require(isinstance(group.get('Description'), str), 'group-description-schema')


def sg_decision(captured: dict, current: dict | None, groups_in_vpc: list[dict],
                interfaces: list[dict], scope: dict, *, attempted: bool) -> str:
    """Require exact captured group, no interfaces and no incoming SG references.

    groups_in_vpc must be the complete fresh native VPC inventory, including rule
    lists. AWS API race rejection remains final; no rule removal/detach is allowed.
    """
    _scope(scope); _group_identity(captured, scope)
    require(type(attempted) is bool and isinstance(groups_in_vpc, list)
            and isinstance(interfaces, list), 'group-observation-schema')
    require(interfaces == [], 'group-still-has-interfaces')
    seen, candidates = set(), []
    for group in groups_in_vpc:
        require(isinstance(group, dict) and isinstance(group.get('GroupId'), str)
                and re.fullmatch('sg-[0-9a-f]+', group['GroupId']) and group['GroupId'] not in seen,
                'group-inventory-schema')
        seen.add(group['GroupId'])
        require(group.get('VpcId') == scope['vpc_id'], 'group-inventory-vpc')
        for key in ('IpPermissions', 'IpPermissionsEgress'):
            permissions = group.get(key)
            require(isinstance(permissions, list), 'group-rule-list')
            for permission in permissions:
                require(isinstance(permission, dict) and isinstance(permission.get('UserIdGroupPairs', []), list), 'group-reference-schema')
                for pair in permission.get('UserIdGroupPairs', []):
                    require(isinstance(pair, dict) and isinstance(pair.get('GroupId'), str), 'group-reference-schema')
                    require(group['GroupId'] == scope['group_id'] or pair['GroupId'] != scope['group_id'], 'other-group-reference')
        if group['GroupId'] == scope['group_id']:
            candidates.append(group)
    if current is None:
        require(not candidates, 'group-query-disagreement')
        return 'confirmed-absent'
    _group_identity(current, scope)
    require(candidates == [current] and current == captured, 'captured-group-drift')
    require(not attempted, 'group-attempt-already-consumed')
    return 'delete-once'
