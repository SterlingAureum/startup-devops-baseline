"""Pure exact reviewed-address/definition/ID destroy gate; no Terraform calls."""
from __future__ import annotations
import json
from guarded_runtime_rules import require, state_addresses


def managed_inventory(state: dict) -> dict[str, dict]:
    """Derive exact current managed definitions from strict v4 state."""
    classified = state_addresses(state)
    managed = {}
    for row in state['resources']:
        if row.get('mode', 'managed') != 'managed':
            continue
        module = row.get('module', '')
        base = (module+'.' if module else '')+row['type']+'.'+row['name']
        for instance in row['instances']:
            address = base
            if 'index_key' in instance:
                address += '['+json.dumps(instance['index_key'], ensure_ascii=False)+']'
            attrs = instance.get('attributes')
            require(address in classified and isinstance(attrs, dict)
                    and isinstance(attrs.get('id'), str) and bool(attrs['id']), 'managed-state-id')
            managed[address] = {'address':address,'module':module,'type':row['type'],
                                'name':row['name'],'id':attrs['id']}
    return managed


def _reviewed(rows: tuple[dict, ...], current: dict[str, dict]) -> dict[str, dict]:
    require(isinstance(rows, tuple) and bool(rows), 'reviewed-resource-set')
    expected = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'address','module','type','name','id'}
                and all(isinstance(x, str) for x in row.values()), 'reviewed-definition-schema')
        address = row['address']
        require(address in current and address not in expected and row == current[address],
                'reviewed-state-definition-or-id-drift')
        expected[address] = row
    return expected


def _delete(item: dict, expected: dict[str, dict]) -> str:
    require(isinstance(item, dict) and isinstance(item.get('address'), str)
            and item['address'] in expected, 'unreviewed-plan-address')
    row = expected[item['address']]
    module = item.get('module_address')
    require((module is None or isinstance(module, str)) and (module or '') == row['module']
            and item.get('mode') == 'managed' and item.get('type') == row['type'], 'plan-definition-drift')
    change = item.get('change')
    require(isinstance(change, dict) and change.get('actions') == ['delete']
            and 'after' in change and change['after'] is None and isinstance(change.get('before'), dict)
            and change['before'].get('id') == row['id'], 'plan-action-or-before-id-drift')
    return row['address']


def validate_destroy_plan(plan: dict, state: dict, reviewed_resources: tuple[dict, ...], *,
                          final: bool, reviewed_remote_absence: tuple[str, ...]) -> dict:
    """Cover exact reviewed managed state by deletes or explicitly reviewed drift.

    final requires review of every current managed address. Targeted stages use
    an explicit dependency closure, never a module prefix or historical count.
    Remote absence needs separate native evidence in the adapter; drift JSON alone
    cannot authorize it. This narrow gate rejects data/no-op/extra changes and
    delete/drift overlap rather than inferring approval from an unfamiliar shape.
    Returned addresses are private; only aggregate counts belong in public output.
    """
    require(type(final) is bool and isinstance(plan, dict)
            and isinstance(plan.get('resource_changes'), list)
            and isinstance(plan.get('resource_drift', []), list), 'destroy-plan-schema')
    current = managed_inventory(state)
    expected = _reviewed(reviewed_resources, current)
    require(not final or set(expected) == set(current), 'final-review-must-cover-managed-state')
    require(isinstance(reviewed_remote_absence, tuple)
            and all(isinstance(a, str) for a in reviewed_remote_absence)
            and len(reviewed_remote_absence) == len(set(reviewed_remote_absence))
            and set(reviewed_remote_absence) <= set(expected), 'reviewed-absence-schema')
    drift = set()
    for item in plan.get('resource_drift', []):
        address = _delete(item, expected)
        require(address not in drift and address in reviewed_remote_absence, 'unreviewed-or-duplicate-drift')
        drift.add(address)
    require(drift == set(reviewed_remote_absence), 'reviewed-absence-plan-mismatch')
    deleted = set()
    for item in plan['resource_changes']:
        address = _delete(item, expected)
        require(address not in deleted and address not in drift, 'duplicate-or-overlapping-delete')
        deleted.add(address)
    require(deleted | drift == set(expected), 'missing-reviewed-delete')
    return {'deleted':sorted(deleted),'drift':sorted(drift),
            'managed_delete_count':len(deleted),'reviewed_remote_absence_count':len(drift)}
