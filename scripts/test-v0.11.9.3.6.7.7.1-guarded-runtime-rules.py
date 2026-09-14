#!/usr/bin/env python3
"""Pure-rule tests and frozen-source parity; no live AWS or Terraform commands."""
from __future__ import annotations
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import guarded_runtime_rules as rules

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, HERE/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('frozen_audit_rules_parity', 'execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py')
state_fixture = load('frozen_state_fixture_parity', 'test-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py')
dev = load('frozen_dev_clock_parity', 'execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py')

FIRST = '2026-09-14T01:00:00Z'
END = '2026-09-14T05:00:00Z'
CURRENT = '2026-09-14T02:00:00Z'


class ClockTests(unittest.TestCase):
    def test_strict_utc_matches_frozen_test_and_normal_dev_utc(self):
        for value in (FIRST, END, CURRENT, '2024-02-29T23:59:59Z'):
            with self.subTest(value=value):
                self.assertEqual(rules.parse_utc(value), audit.utc(value))
                self.assertEqual(rules.parse_utc(value), dev.parse_utc(value))

    def test_offset_fraction_bad_calendar_and_nonstring_are_rejected(self):
        for value in ('2026-09-14T01:00:00+00:00', '2026-09-14T01:00:00.1Z',
                      '2026-02-30T01:00:00Z', '2026-09-14T24:00:00Z', '', None, 1):
            with self.subTest(value=value), self.assertRaises(rules.RuleViolation):
                rules.parse_utc(value)

    def test_window_parity_including_reserve_boundary(self):
        c = {'maximumWindowSeconds': 14400, 'minimumStartRemainingSeconds': 900}
        args = SimpleNamespace(start_utc=FIRST, end_utc=END)
        for current in (FIRST, CURRENT, '2026-09-14T04:45:00Z',
                        '2026-09-14T04:45:01Z', '2026-09-14T00:59:59Z', END):
            old_ok = True
            try:
                expected = audit.window(args, c, lambda: rules.parse_utc(current))
            except audit.Stop:
                old_ok = False
            with self.subTest(current=current):
                if old_ok:
                    self.assertEqual(rules.validate_window(FIRST, END, current,
                        maximum_seconds=14400, minimum_remaining_seconds=900), expected)
                else:
                    with self.assertRaises(rules.RuleViolation):
                        rules.validate_window(FIRST, END, current,
                            maximum_seconds=14400, minimum_remaining_seconds=900)

    def test_invalid_duration_and_policy_are_rejected(self):
        for end in (FIRST, '2026-09-14T00:59:59Z', '2026-09-14T05:00:01Z'):
            with self.subTest(end=end), self.assertRaises(rules.RuleViolation):
                rules.validate_window(FIRST, end, FIRST, maximum_seconds=14400, minimum_remaining_seconds=900)
        for value in (True, 0, -1, 900.0, '900'):
            with self.subTest(value=value), self.assertRaises(rules.RuleViolation):
                rules.validate_window(FIRST, END, FIRST, maximum_seconds=14400, minimum_remaining_seconds=value)

    def test_observation_ttl_inclusive_and_future_observation_rejected(self):
        rules.validate_observation_age(FIRST, CURRENT, ttl_seconds=3600)
        for current in ('2026-09-14T02:00:01Z', '2026-09-14T00:59:59Z'):
            with self.subTest(current=current), self.assertRaises(rules.RuleViolation):
                rules.validate_observation_age(FIRST, current, ttl_seconds=3600)

    def test_proof_exclusive_expiry_and_original_clock_are_enforced(self):
        expires = '2026-09-14T01:15:00Z'
        rules.validate_proof(FIRST, expires, '2026-09-14T01:14:59Z', END, ttl_seconds=900, original_created=FIRST)
        for created, last, instant in (
            (FIRST, expires, expires), (FIRST, expires, '2026-09-14T00:59:59Z'),
            (FIRST, '2026-09-14T01:16:00Z', FIRST),
            ('2026-09-14T01:05:00Z', expires, '2026-09-14T01:05:00Z')):
            with self.subTest(created=created, last=last, instant=instant), self.assertRaises(rules.RuleViolation):
                rules.validate_proof(created, last, instant, END, ttl_seconds=900, original_created=FIRST)

    def test_proof_expiry_is_clamped_to_deadline(self):
        stop = '2026-09-14T01:10:00Z'
        rules.validate_proof(FIRST, stop, '2026-09-14T01:09:59Z', stop, ttl_seconds=900, original_created=FIRST)
        with self.assertRaises(rules.RuleViolation):
            rules.validate_proof(FIRST, '2026-09-14T01:15:00Z', FIRST, stop, ttl_seconds=900, original_created=FIRST)

    def test_reset_creation_and_expiry_together_cannot_renew_bound_proof(self):
        with self.assertRaisesRegex(rules.RuleViolation, 'proof-creation-drift'):
            rules.validate_proof('2026-09-14T02:00:00Z', '2026-09-14T02:15:00Z',
                CURRENT, END, ttl_seconds=900, original_created=FIRST)
        with self.assertRaisesRegex(rules.RuleViolation, 'proof-clock-overflow'):
            rules.validate_proof('9999-12-31T23:59:58Z', '9999-12-31T23:59:59Z',
                '9999-12-31T23:59:58Z', '9999-12-31T23:59:59Z', ttl_seconds=900,
                original_created='9999-12-31T23:59:58Z')


class ConfirmationTests(unittest.TestCase):
    def policy(self, target, execute=False):
        prefix = 'CONFIRM_'+target.upper().replace('-', '_')+'_RESIDUAL_COST_AUDIT_'
        policy = {prefix+'PREFLIGHT': 'observe-reviewed-'+target+'-residual-cost-audit-preflight'}
        if execute:
            policy[prefix+'EXECUTION'] = 'execute-reviewed-'+target+'-residual-cost-audit-once'
        return policy

    def test_test_phase_values_match_frozen_environment_rule(self):
        for phase in ('preflight', 'verify', 'execute'):
            policy = self.policy('aws-test', phase == 'execute')
            env = {'AWS_ENVIRONMENT': 'aws-test', 'EXPECTED_AWS_ACCOUNT_ID': '0'*12, **policy}
            rules.validate_confirmations(env, 'aws-test', policy)
            audit.environment_check(phase, env)

    def test_dev_test_prod_rules_are_explicit_and_do_not_enable_an_adapter(self):
        for target in ('aws-dev', 'aws-test', 'aws-prod'):
            policy = self.policy(target)
            rules.validate_confirmations({'AWS_ENVIRONMENT': target, **policy}, target, policy)
            other = 'aws-test' if target != 'aws-test' else 'aws-dev'
            with self.assertRaises(rules.RuleViolation):
                rules.validate_confirmations({'AWS_ENVIRONMENT': other, **policy}, target, policy)

    def test_missing_once_suffix_or_execute_flag_fails_parity(self):
        policy = self.policy('aws-test', True)
        for value in (None, '', policy[next(k for k in policy if k.endswith('EXECUTION'))][:-5]):
            env = {'AWS_ENVIRONMENT': 'aws-test', 'EXPECTED_AWS_ACCOUNT_ID': '0'*12, **policy}
            key = next(k for k in policy if k.endswith('EXECUTION'))
            if value is None:
                env.pop(key)
            else:
                env[key] = value
            with self.subTest(value=value):
                with self.assertRaises(rules.RuleViolation): rules.validate_confirmations(env, 'aws-test', policy)
                with self.assertRaises(audit.Stop): audit.environment_check('execute', env)

    def test_unrelated_empty_confirmation_and_overrides_fail_parity(self):
        policy = self.policy('aws-test')
        for key in ('CONFIRM_AWS_DEV_APPLY', 'CONFIRM_AWS_TEST_APPLY', 'AWS_ENDPOINT_URL',
                    'AWS_ENDPOINT_URL_EC2', 'TF_VAR_environment', 'TF_CLI_ARGS_plan', 'TF_WORKSPACE', 'AWS_TEST_APPLY_MODE'):
            env = {'AWS_ENVIRONMENT': 'aws-test', 'EXPECTED_AWS_ACCOUNT_ID': '0'*12, **policy, key: ''}
            with self.subTest(key=key):
                with self.assertRaises(rules.RuleViolation): rules.validate_confirmations(env, 'aws-test', policy)
                with self.assertRaises(audit.Stop): audit.environment_check('verify', env)

    def test_empty_cross_environment_or_invalid_policy_is_rejected(self):
        for target, policy in (('aws-test', {}), ('local', {}),
                               ('aws-test', self.policy('aws-dev')), ('aws-test', {'CONFIRM_AWS_TEST_X': ''})):
            with self.subTest(target=target, policy=policy), self.assertRaises(rules.RuleViolation):
                rules.validate_confirmations({'AWS_ENVIRONMENT': target}, target, policy)


class AbsenceTests(unittest.TestCase):
    def line(self, code='NoSuchBucket', api='ListObjectVersions', annotation=''):
        return ('\nAn error occurred ('+code+') when calling the '+api+' operation'+annotation+': fixture only\n').encode()

    def test_operation_specific_absence_matches_frozen_parser(self):
        for code, op, api in (('NoSuchBucket','list-object-versions','ListObjectVersions'),
            ('ResourceNotFoundException','describe-secret','DescribeSecret'),
            ('NoSuchEntity','get-open-id-connect-provider','GetOpenIDConnectProvider'),
            ('InvalidVolume.NotFound','describe-volumes','DescribeVolumes'),
            ('AWS.SimpleQueueService.NonExistentQueue','get-queue-attributes','GetQueueAttributes')):
            for annotation in ('', ' (reached max retries: 0)'):
                raw = self.line(code, api, annotation)
                with self.subTest(code=code, annotation=annotation):
                    self.assertTrue(rules.absence_error(raw, b'', op, (code,)))
                    self.assertEqual(rules.absence_error(raw, b'', op, (code,)), audit.absence_error(raw, b'', op, (code,)))

    def test_positive_malformed_extra_and_permission_errors_match_frozen_rejection(self):
        invalid = [self.line(annotation=x) for x in (' (reached max retries: 1)', ' (reached max retries: -1)',
                   ' (reached max retries: 00)', ' (reached max retries: 0) (reached max retries: 0)')]
        invalid += [self.line('AccessDenied'), self.line(api='DescribeSecret'), self.line()+self.line(),
                    b'warning\n'+self.line(), b'connection timed out\n']
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertFalse(rules.absence_error(raw, b'', 'list-object-versions', ('NoSuchBucket',)))
                self.assertEqual(rules.absence_error(raw, b'', 'list-object-versions', ('NoSuchBucket',)),
                                 audit.absence_error(raw, b'', 'list-object-versions', ('NoSuchBucket',)))

    def test_nonempty_stdout_and_undefined_policy_are_rejected(self):
        for stdout in (b'{}', b'null', b'partial output'):
            self.assertFalse(rules.absence_error(self.line(), stdout, 'list-object-versions', ('NoSuchBucket',)))
        for operation, allowed in (('ListObjectVersions', ('NoSuchBucket',)), ('', ('NoSuchBucket',)), ('list-object-versions', ())):
            self.assertFalse(rules.absence_error(self.line(), b'', operation, allowed))


class StateTests(unittest.TestCase):
    def test_legacy_fixture_aggregate_parity_and_explicit_extra_data_scope(self):
        inputs = state_fixture.fixture()
        old = state_fixture.MODULE.classify_state(*inputs)
        new = rules.classify_state(*inputs)
        self.assertEqual({k: new[k] for k in old}, old)
        rules.validate_post_apply(*inputs, reviewed_extra_data=('data.aws_partition.current',))
        with self.assertRaises(rules.RuleViolation):
            rules.validate_post_apply(*inputs, reviewed_extra_data=())

    def test_exact_historical_96_90_103_80_fixture_replayed_without_incident_waiver(self):
        original = state_fixture.MODULE.classify_state
        reports = []
        def parity(plan, state, listed):
            old = original(plan, state, listed)
            new = rules.classify_state(plan, state, listed)
            self.assertEqual({k:new[k] for k in old}, old)
            reports.append(new)
            return old
        with mock.patch.object(state_fixture.MODULE, 'classify_state', side_effect=parity):
            state_fixture.StateClassificationTests().test_exact_incident_shape_is_accepted_end_to_end()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['unexpected_data_address_count'], 7)

    def test_nested_indexed_modules_and_quoted_for_each_keys(self):
        for key in ('prod', 'quoted"key', 'back\\slash', '键'):
            module = 'module.parent[0].module.child["test"]'
            state = {'version':4, 'resources':[{'module':module,'mode':'managed','type':'aws_subnet','name':'main','instances':[{'index_key':key}]}]}
            address = module+'.aws_subnet.main['+json.dumps(key, ensure_ascii=False)+']'
            self.assertEqual(rules.state_addresses(state), {address:('managed','aws_subnet')})
            plan = {'resource_changes':[{'address':address,'change':{'actions':['create']}}]}
            rules.validate_post_apply(plan, state, (address+'\n').encode(), reviewed_extra_data=())

    def test_missing_create_and_extra_managed_are_diagnostic_then_rejected(self):
        plan, state, listed = state_fixture.fixture()
        plan['resource_changes'][0]['address'] = 'aws_vpc.other'
        report = rules.classify_state(plan, state, listed)
        self.assertEqual(report['missing_planned_create_count'], 1)
        self.assertEqual(report['unexpected_managed_address_count'], 1)
        with self.assertRaises(rules.RuleViolation):
            rules.validate_post_apply(plan, state, listed, reviewed_extra_data=('data.aws_partition.current',))

    def test_state_list_mismatch_and_duplicate_lines_are_intentional_strict_failures(self):
        plan, state, listed = state_fixture.fixture()
        for value in (listed+b'aws_vpc.main\n', listed+b'aws_vpc.unknown\n', b'', b'\xff'):
            with self.subTest(value=value), self.assertRaises(rules.RuleViolation): rules.classify_state(plan,state,value)

    def test_duplicate_definitions_instances_invalid_indexes_and_deposed_fail(self):
        _, original, _ = state_fixture.fixture()
        variants=[]
        x=copy.deepcopy(original);x['resources'].append(copy.deepcopy(x['resources'][0]));variants.append(x)
        x=copy.deepcopy(original);x['resources'][0]['instances'].append({});variants.append(x)
        for key in (True, -1, 1.5, None):
            x=copy.deepcopy(original);x['resources'][0]['instances'][0]['index_key']=key;variants.append(x)
        x=copy.deepcopy(original);x['resources'][0]['instances'][0]['deposed']='old';variants.append(x)
        x=copy.deepcopy(original);x['resources'][0]['mode']='unknown';variants.append(x)
        for x in variants:
            with self.subTest(x=x), self.assertRaises(rules.RuleViolation): rules.state_addresses(x)

    def test_duplicate_plan_addresses_and_malformed_actions_are_rejected(self):
        plan, state, listed = state_fixture.fixture()
        for actions in ([], ['unknown'], ['create', 'read'], 'create', [True]):
            x=copy.deepcopy(plan);x['resource_changes'][0]['change']['actions']=actions
            with self.subTest(actions=actions), self.assertRaises(rules.RuleViolation): rules.classify_state(x,state,listed)
        x=copy.deepcopy(plan);x['resource_changes'].append(copy.deepcopy(x['resource_changes'][0]))
        with self.assertRaises(rules.RuleViolation): rules.classify_state(x,state,listed)

    def test_post_apply_rejects_update_delete_replacement_and_data_create(self):
        plan, state, listed = state_fixture.fixture()
        for actions in (['update'],['delete'],['create','delete'],['delete','create']):
            x=copy.deepcopy(plan);x['resource_changes'][0]['change']['actions']=actions
            with self.subTest(actions=actions), self.assertRaises(rules.RuleViolation):
                rules.validate_post_apply(x,state,listed,reviewed_extra_data=('data.aws_partition.current',))
        x=copy.deepcopy(plan);x['resource_changes'][2]['change']['actions']=['create']
        with self.assertRaises(rules.RuleViolation): rules.validate_post_apply(x,state,listed,reviewed_extra_data=('data.aws_partition.current',))

    def test_data_whitelist_is_exact_address_not_type_count_or_default(self):
        inputs=state_fixture.fixture()
        for approved in (('data.aws_partition.other',), ('data.aws_partition.current','data.aws_partition.other'),
                          ('data.aws_partition.current','data.aws_partition.current'), ['data.aws_partition.current']):
            with self.subTest(approved=approved), self.assertRaises(rules.RuleViolation):
                rules.validate_post_apply(*inputs, reviewed_extra_data=approved)

    def test_empty_state_noop_and_managed_read_semantics(self):
        rules.validate_post_apply({'resource_changes':[]}, {'version':4,'resources':[]}, b'', reviewed_extra_data=())
        plan,state,listed=state_fixture.fixture()
        plan['resource_changes'][0]['change']['actions']=['no-op']
        rules.validate_post_apply(plan,state,listed,reviewed_extra_data=('data.aws_partition.current',))
        plan['resource_changes'][0]['change']['actions']=['read']
        with self.assertRaises(rules.RuleViolation): rules.validate_post_apply(plan,state,listed,reviewed_extra_data=('data.aws_partition.current',))


class InputAndPurityTests(unittest.TestCase):
    def test_json_duplicates_nonfinite_overflow_invalid_and_nonobjects_are_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'[]', b'bad', b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(rules.RuleViolation): rules.json_object(raw)
        self.assertEqual(rules.json_object(b'{"a":1.5}'), {'a':1.5})

    def test_errors_are_redacted_and_inputs_are_not_modified(self):
        plan,state,listed=state_fixture.fixture();snapshot=copy.deepcopy((plan,state))
        rules.classify_state(plan,state,listed)
        self.assertEqual((plan,state),snapshot)
        with self.assertRaises(rules.RuleViolation) as caught: rules.parse_utc('private-raw-value')
        self.assertNotIn('private-raw-value',str(caught.exception))

    def test_module_has_no_io_environment_or_clock_reads(self):
        tree=ast.parse((HERE/'guarded_runtime_rules.py').read_text())
        allowed={'__future__','collections','datetime','json','re','typing'}
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): self.assertTrue(all(x.name in allowed for x in n.names))
            if isinstance(n,ast.ImportFrom): self.assertIn(n.module,allowed)
            if isinstance(n,ast.Call):
                if isinstance(n.func,ast.Name): self.assertNotIn(n.func.id,{'open','eval','exec','__import__','print','input'})
                if isinstance(n.func,ast.Attribute): self.assertNotIn(n.func.attr,{'now','utcnow','today','read_bytes','read_text','write_bytes','write_text','getenv','run','Popen'})


if __name__ == '__main__':
    unittest.main()
