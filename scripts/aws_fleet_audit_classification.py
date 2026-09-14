"""Pure Fleet response classification for separately scoped read-only auditors.

No transport, mutation, credentials or environment assumptions live here. Callers
must first prove native compute/network absence, bind ownership and verify every
returned instance ID against captured scope and its current native state.
"""
import math
import re

class FleetClassificationError(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise FleetClassificationError(reason)

def classify_fleet(row, expected_id, project, environment, cluster):
    """Return (category, launched_instance_ids); never assert live absence itself."""
    require(isinstance(row, dict) and row.get('FleetId') == expected_id,
            'fleet-response-identity')
    state = row.get('FleetState')
    if state in ('deleted', 'deleted_terminating'):
        return 'terminal', ()
    require(state == 'active' and row.get('Type') == 'instant',
            'nonterminal-or-unknown-fleet-type')
    require(row.get('ActivityStatus') == 'fulfilled' and
            row.get('ReplaceUnhealthyInstances') is False,
            'instant-request-not-complete')
    tags = row.get('Tags')
    require(isinstance(tags, list), 'native-fleet-tags-required')
    values = {}
    for tag in tags:
        require(isinstance(tag, dict) and isinstance(tag.get('Key'), str) and
                isinstance(tag.get('Value'), str) and tag['Key'] not in values,
                'invalid-or-duplicate-fleet-tag')
        values[tag['Key']] = tag['Value']
    require((values.get('Project') == project and values.get('Environment') == environment)
            or values.get('elbv2.k8s.aws/cluster') == cluster
            or values.get('kubernetes.io/cluster/' + cluster) in ('owned', 'shared'),
            'native-fleet-ownership-mismatch')
    capacities = [row.get('FulfilledCapacity'), row.get('FulfilledOnDemandCapacity')]
    require(all(isinstance(x, (int, float)) and not isinstance(x, bool) and
                math.isfinite(x) and x >= 0 for x in capacities),
            'invalid-instant-capacity-metadata')
    require(capacities[1] <= capacities[0], 'inconsistent-instant-capacity-metadata')
    groups = row.get('Instances')
    require(isinstance(groups, list), 'instant-instance-list-required')
    ids = []
    for group in groups:
        require(isinstance(group, dict) and isinstance(group.get('InstanceIds'), list)
                and bool(group['InstanceIds']), 'instant-instance-ids-required')
        for iid in group['InstanceIds']:
            require(isinstance(iid, str) and re.fullmatch(r'i-[0-9a-f]+', iid),
                    'instant-instance-id-format')
            require(iid not in ids, 'duplicate-instant-instance-id')
            ids.append(iid)
    require(bool(ids) or capacities == [0, 0], 'positive-capacity-without-instance-ids')
    return 'instant-history', tuple(ids)
