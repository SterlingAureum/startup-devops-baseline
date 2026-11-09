"""Pure rules for future explicitly scoped guarded-runtime adapters.

No clock reads, file access, environment reads, transport or mutation. Passing a
rule validates supplied data only; it never grants an operation's authorization.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Mapping


class RuleViolation(ValueError):
    """A stable, redacted reason; never include raw inputs in the exception."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuleViolation(reason)


def positive_seconds(value: int) -> None:
    require(type(value) is int and value > 0, 'positive-seconds-required')


def parse_utc(value: str) -> datetime:
    require(isinstance(value, str) and re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value) is not None,
        'utc-format')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        raise RuleViolation('utc-calendar') from None


def validate_window(start: str, end: str, current: str, *,
                    maximum_seconds: int, minimum_remaining_seconds: int) -> datetime:
    """Require an active bounded start window, including the exact reserve edge."""
    positive_seconds(maximum_seconds)
    positive_seconds(minimum_remaining_seconds)
    first, last, instant = map(parse_utc, (start, end, current))
    require(0 < (last-first).total_seconds() <= maximum_seconds, 'window-duration')
    require(first <= instant and (last-instant).total_seconds() >= minimum_remaining_seconds,
            'window-start-expired')
    return last


def validate_observation_age(observed: str, current: str, *, ttl_seconds: int) -> None:
    """Observation TTL is inclusive, matching the frozen test preflight rule."""
    positive_seconds(ttl_seconds)
    age = (parse_utc(current)-parse_utc(observed)).total_seconds()
    require(0 <= age <= ttl_seconds, 'observation-expired')


def validate_proof(created: str, expires: str, current: str, deadline: str, *,
                   ttl_seconds: int, original_created: str) -> datetime:
    """Use original creation time, exact expiry binding and an exclusive expiry."""
    positive_seconds(ttl_seconds)
    first, last, instant, stop = map(parse_utc, (created, expires, current, deadline))
    require(first == parse_utc(original_created), 'proof-creation-drift')
    try:
        bound = min(stop, first+timedelta(seconds=ttl_seconds))
    except OverflowError:
        raise RuleViolation('proof-clock-overflow') from None
    require(first < stop and last == bound,
            'proof-expiry-binding')
    require(first <= instant < last, 'proof-expired')
    return last


def validate_confirmations(environment: Mapping[str, str], target: str,
                           required: Mapping[str, str]) -> None:
    """Validate caller-supplied phase values; no inherited or default scope.

    Even an unrelated empty CONFIRM variable fails. Target and exact phase mapping
    must come from a reviewed adapter. This function performs no account check.
    """
    require(target in ('aws-dev', 'aws-test', 'aws-prod'), 'explicit-environment-required')
    require(isinstance(environment, Mapping) and isinstance(required, Mapping)
            and bool(required), 'phase-policy-required')
    require(all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()),
            'environment-schema')
    prefix = 'CONFIRM_'+target.upper().replace('-', '_')+'_'
    require(all(isinstance(k, str) and k.startswith(prefix) and isinstance(v, str)
                and bool(v) for k, v in required.items()), 'phase-policy-scope')
    require(environment.get('AWS_ENVIRONMENT') == target, 'environment-mismatch')
    require(all(environment.get(k) == v for k, v in required.items()), 'phase-confirmation')
    require(not any(k.startswith('CONFIRM_') and k not in required for k in environment),
            'unrelated-confirmation')
    require(not any(k.startswith(('AWS_ENDPOINT_URL', 'TF_CLI_ARGS', 'TF_VAR_'))
                    or k in ('AWS_TEST_APPLY_MODE', 'TF_WORKSPACE') for k in environment),
            'endpoint-or-terraform-override')


def absence_error(stderr: bytes, stdout: bytes, operation: str,
                  allowed: tuple[str, ...]) -> bool:
    """Recognize an exact native absence envelope, not an arbitrary failed call.

    The adapter must bind allowed codes to the service operation and target. False
    requires review; no retries, service calls or resource-absence claims occur here.
    """
    if not (isinstance(stderr, bytes) and isinstance(stdout, bytes)
            and isinstance(operation, str) and re.fullmatch('[a-z]+(?:-[a-z]+)*', operation)
            and isinstance(allowed, tuple) and bool(allowed)
            and all(isinstance(c, str) and re.fullmatch('[A-Za-z0-9_.-]+', c) for c in allowed)):
        return False
    if stdout.strip():
        return False
    lines = [line for line in stderr.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    match = re.fullmatch(
        rb'An error occurred \(([A-Za-z0-9_.-]+)\) when calling the '
        rb'([A-Za-z0-9]+) operation(?: \(reached max retries: 0\))?:[^\r\n]*', lines[0])
    return bool(match and match[1].decode() in allowed
                and match[2].decode().lower() == operation.replace('-', ''))


def json_object(raw: bytes) -> dict:
    """Reject duplicates and all nonfinite numbers, including exponent overflow."""
    require(isinstance(raw, bytes), 'json-bytes-required')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate-json-key')
            result[key] = value
        return result
    def reject(_):
        raise RuleViolation('nonfinite-json')
    def number(value):
        parsed = float(value)
        require(parsed != float('inf') and parsed != float('-inf'), 'nonfinite-json')
        return parsed
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=number)
    except RuleViolation:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise RuleViolation('invalid-json') from None
    require(isinstance(value, dict), 'json-object-required')
    return value


_IDENTIFIER = r'[A-Za-z_][A-Za-z0-9_-]*'
_INDEX = r'\[(?:[0-9]+|"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*")\]'
_MODULE = rf'(?:module\.{_IDENTIFIER}(?:{_INDEX})?\.)*'
_ADDRESS = re.compile(rf'{_MODULE}(?:data\.)?{_IDENTIFIER}\.{_IDENTIFIER}(?:{_INDEX})?')


def state_addresses(state: dict) -> dict[str, tuple[str, str]]:
    """Derive exact current v4 instance addresses, including count/for_each keys.

    This supports ASCII Terraform identifiers and JSON string instance keys.
    Deposed instances, duplicate definitions and unknown modes fail closed. It
    does not prove remote existence, ownership or before-ID equality.
    """
    require(isinstance(state, dict) and type(state.get('version')) is int
            and state['version'] == 4 and isinstance(state.get('resources'), list), 'state-v4-schema')
    result, definitions = {}, set()
    for row in state['resources']:
        require(isinstance(row, dict), 'state-resource-schema')
        mode = row.get('mode', 'managed')
        require(mode in ('managed', 'data'), 'state-mode')
        require(all(isinstance(row.get(k), str) and re.fullmatch(_IDENTIFIER, row[k])
                    for k in ('type', 'name')), 'state-definition')
        module = row.get('module', '')
        require(isinstance(module, str) and (not module or re.fullmatch(_MODULE, module+'.')),
                'state-module')
        base = (module+'.' if module else '')+('data.' if mode == 'data' else '')+row['type']+'.'+row['name']
        require(base not in definitions, 'duplicate-state-definition')
        definitions.add(base)
        require(isinstance(row.get('instances'), list), 'state-instance-list')
        for instance in row['instances']:
            require(isinstance(instance, dict) and instance.get('deposed') is None,
                    'deposed-or-invalid-instance')
            address = base
            if 'index_key' in instance:
                key = instance['index_key']
                require((type(key) is int and key >= 0) or isinstance(key, str), 'state-index')
                address += '['+json.dumps(key, ensure_ascii=False)+']'
            require(_ADDRESS.fullmatch(address) is not None and address not in result,
                    'duplicate-or-invalid-state-address')
            result[address] = (mode, row['type'])
    return result


def classify_state(plan: dict, state: dict, state_list_bytes: bytes) -> dict:
    """Separate planned create coverage and unexpected managed/data instances.

    Returns exact private address sets alongside the legacy aggregate keys. A
    classifier result is diagnostic; only validate_post_apply checks create/read/
    no-op phase semantics and exact reviewed extra-data scope. Never print address
    sets as public evidence. Listed/current state mismatch is a schema failure.
    """
    require(isinstance(plan, dict) and isinstance(plan.get('resource_changes'), list), 'plan-schema')
    expected, creates, action_sets = set(), set(), set()
    for row in plan['resource_changes']:
        require(isinstance(row, dict) and isinstance(row.get('address'), str)
                and _ADDRESS.fullmatch(row['address']) is not None, 'plan-address')
        address = row['address']
        require(address not in expected and isinstance(row.get('change'), dict), 'duplicate-or-invalid-plan-change')
        actions = row['change'].get('actions')
        require(isinstance(actions, list) and bool(actions) and all(isinstance(x, str) for x in actions)
                and tuple(actions) in (('create',), ('read',), ('no-op',), ('update',), ('delete',),
                                        ('delete', 'create'), ('create', 'delete')), 'plan-actions')
        expected.add(address); action_sets.add(tuple(actions))
        if actions == ['create']:
            creates.add(address)
    require(isinstance(state_list_bytes, bytes), 'state-list-bytes')
    try:
        lines = [line for line in state_list_bytes.decode('utf-8').splitlines() if line]
    except UnicodeError:
        raise RuleViolation('state-list-encoding') from None
    listed = set(lines)
    require(len(listed) == len(lines) and all(_ADDRESS.fullmatch(x) for x in lines),
            'duplicate-or-invalid-state-list')
    mapping = state_addresses(state)
    require(listed == set(mapping), 'state-list-instance-mismatch')
    unexpected = listed-expected
    data = sorted(a for a in unexpected if mapping[a][0] == 'data')
    managed = sorted(a for a in unexpected if mapping[a][0] == 'managed')
    counts = Counter(mapping[a][1] for a in data)
    return {
        'plan_resource_change_count': len(expected), 'plan_create_address_count': len(creates),
        'state_list_address_count': len(listed), 'state_resource_block_count': len(state['resources']),
        'state_resource_instance_count': len(mapping), 'classified_state_list_address_count': len(listed),
        'missing_planned_create_count': len(creates-listed), 'unexpected_state_address_count': len(unexpected),
        'unexpected_managed_address_count': len(managed), 'unexpected_data_address_count': len(data),
        'unexpected_unclassified_address_count': 0, 'unexpected_data_type_counts': dict(sorted(counts.items())),
        'missing_planned_create_addresses': sorted(creates-listed), 'unexpected_managed_addresses': managed,
        'unexpected_data_addresses': data, 'plan_action_sets': sorted(action_sets),
    }


def validate_post_apply(plan: dict, state: dict, state_list_bytes: bytes, *,
                        reviewed_extra_data: tuple[str, ...]) -> dict:
    """Require complete create coverage and exact reviewed extra-data addresses.

    Recompute internally; caller-edited aggregate counters cannot authorize a
    pass. The reviewed data set is run-specific, never a default type/count waiver.
    """
    require(isinstance(reviewed_extra_data, tuple) and all(isinstance(x, str) for x in reviewed_extra_data)
            and len(set(reviewed_extra_data)) == len(reviewed_extra_data), 'reviewed-data-schema')
    report = classify_state(plan, state, state_list_bytes)
    require(all(actions in (('create',), ('read',), ('no-op',)) for actions in report['plan_action_sets']),
            'post-apply-plan-actions')
    mapping = state_addresses(state)
    for row in plan['resource_changes']:
        if row['address'] in mapping:
            mode = mapping[row['address']][0]
            require(row['change']['actions'] != ['create'] or mode == 'managed', 'data-create-action')
            require(row['change']['actions'] != ['read'] or mode == 'data', 'managed-read-action')
    require(report['missing_planned_create_count'] == 0, 'missing-planned-create')
    require(report['unexpected_managed_address_count'] == 0, 'unexpected-managed-state')
    require(set(reviewed_extra_data) == set(report['unexpected_data_addresses']), 'unreviewed-data-state')
    return report
