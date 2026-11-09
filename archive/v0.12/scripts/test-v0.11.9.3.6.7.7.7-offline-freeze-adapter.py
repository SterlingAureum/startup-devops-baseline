#!/usr/bin/env python3
"""Fixed-fake Application freeze adapter and eight-stage chain tests."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import guarded_cleanup_simulation_v6775 as cleanup_adapter
import guarded_freeze_simulation_v6777 as m
import guarded_runtime_simulation_v6774 as destroy_adapter
from guarded_attempt_journal import AttemptJournal
from guarded_cleanup_rules import CLEANUP_STEPS
from guarded_runtime_rules import RuleViolation


ROOT = Path(__file__).resolve().parent.parent
T = '2026-09-16T05:00:00Z'
EXPIRES = '2026-09-16T05:15:00Z'
END = '2026-09-16T07:00:00Z'
MAIN = 'a' * 40


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def uid(number):
    return f'00000000-0000-0000-0000-{number:012d}'


def app(name, number):
    return {
        'name': name,
        'namespace': 'argocd',
        'uid': uid(number),
        'resource_version': str(100 + number),
        'source_sha256': m.sha(('source-' + name).encode()),
        'destination_sha256': m.sha(('destination-' + name).encode()),
        'automated_sync_enabled': True,
        'finalizers': ['resources-finalizer.argocd.argoproj.io'],
        'deletion_requested': False,
        'active_operation': False,
    }


def scenario(directory, environment='aws-test'):
    root_name = 'startup-devops-' + environment + '-root'
    applications = [app(root_name, 1), app('child-a', 2), app('child-b', 3)]
    inputs = {
        'environment': environment,
        'region': 'us-east-1',
        'account': '0' * 12,
        'cluster': 'fixture-' + environment.removeprefix('aws-'),
        'budget_limit_usd': '36.00',
    }
    state = {'version': 4, 'resources': []}
    scope = {'environment': environment, 'phase': m.PHASE,
             'root_name': root_name, 'applications': applications}
    artifacts = {'inputs': raw(inputs), 'scope': raw(scope), 'state': raw(state)}
    approval = {
        'schema': 'offline-freeze-approval-v1',
        'simulation_only': True,
        'environment': environment,
        'phase': m.PHASE,
        'main': MAIN,
        'hashes': {key: m.sha(value) for key, value in artifacts.items()},
        'journal_directory': str(directory),
        'start_utc': T,
        'end_utc': END,
        'created_at': T,
        'original_created_at': T,
        'expires_at': EXPIRES,
        'budget_limit_usd': '36.00',
    }
    cleanup = {'scope_verified': True, 'inventory_complete': True}
    base = {
        'identity': {key: inputs[key] for key in
                     ('environment', 'region', 'account', 'cluster')},
        'main': MAIN,
        'observed_at': T,
        'inventory_complete': True,
        'estimated_total_usd': '1.00',
        'state_sha256': m.sha(artifacts['state']),
        'cleanup': cleanup,
    }
    observations = {
        'pre': copy.deepcopy(base) | {'applications': copy.deepcopy(applications)},
        'immediate': copy.deepcopy(base) | {'applications': copy.deepcopy(applications)},
    }
    results = {}
    current = copy.deepcopy(applications)
    for index in range(len(applications)):
        label = str(index).zfill(4)
        observations['app-' + label + '-freeze-pre'] = copy.deepcopy(base) | {
            'applications': copy.deepcopy(current)}
        changed = copy.deepcopy(current)
        changed[index]['automated_sync_enabled'] = False
        changed[index]['resource_version'] = str(int(changed[index]['resource_version']) + 1000)
        observations['app-' + label + '-freeze-post'] = copy.deepcopy(base) | {
            'applications': copy.deepcopy(changed)}
        current = changed
        results['freeze-app-' + label] = raw({'success': True})
    observations['frozen'] = copy.deepcopy(base) | {'applications': copy.deepcopy(current)}
    for index in range(len(applications)):
        label = str(index).zfill(4)
        observations['app-' + label + '-orphan-pre'] = copy.deepcopy(base) | {
            'applications': copy.deepcopy(current)}
        orphaned = copy.deepcopy(current)
        orphaned[0]['finalizers'] = []
        orphaned[0]['resource_version'] = str(int(orphaned[0]['resource_version']) + 1000)
        observations['app-' + label + '-orphan-post'] = copy.deepcopy(base) | {
            'applications': copy.deepcopy(orphaned)}
        current = orphaned
        observations['app-' + label + '-delete-post'] = copy.deepcopy(base) | {
            'applications': copy.deepcopy(current[1:])}
        current = current[1:]
        results['orphan-app-' + label] = raw({'success': True})
        results['delete-app-' + label] = raw({'success': True})
    observations['post'] = copy.deepcopy(base) | {
        'applications': [], 'active_application_operations': 0,
        'state_unchanged': True}
    confirmations = {
        'AWS_ENVIRONMENT': environment,
        'CONFIRM_' + environment.upper().replace('-', '_') + '_OFFLINE_FREEZE':
        'simulate-reviewed-' + environment + '-freeze-applications-once',
    }
    return {
        'environment': environment,
        'artifacts': artifacts,
        'approval': approval,
        'observations': {key: raw(value) for key, value in observations.items()},
        'results': results,
        'confirmations': confirmations,
    }


def load_fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FreezeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='freeze-adapter-')
        self.directory = Path(self.temp.name) / 'journal'
        self.directory.mkdir(mode=0o700)
        self.s = scenario(self.directory)
        self.transport = None

    def tearDown(self):
        self.temp.cleanup()

    def run_case(self, case=None, *, directory=None, samples=None, fail_at='',
                 transport=None, approval_hash=None):
        case = case or self.s
        approval = raw(case['approval'])
        self.transport = transport or m.FreezeScenarioTransport(
            case['observations'], case['results'], fail_at=fail_at)
        return m.OfflineFreezeAdapter(case['environment'], MAIN,
            repository_root=ROOT).run(case['artifacts'], approval,
            approval_hash or m.sha(approval),
            journal_directory=directory or self.directory,
            confirmations=case['confirmations'], transport=self.transport,
            clock=m.ScenarioClock(samples or (T,) * 200))

    def change_observation(self, label, function):
        value = json.loads(self.s['observations'][label])
        function(value)
        self.s['observations'][label] = raw(value)

    def change_scope(self, function):
        value = json.loads(self.s['artifacts']['scope'])
        function(value)
        self.s['artifacts']['scope'] = raw(value)
        self.s['approval']['hashes'] = {key: m.sha(value)
                                       for key, value in self.s['artifacts'].items()}

    def snapshot(self):
        marker_path = self.directory / 'attempt.json'
        marker = json.loads(marker_path.read_bytes())
        with AttemptJournal.open(self.directory, marker['binding'],
                m.sha(marker_path.read_bytes()), repository_root=ROOT) as handle:
            return handle.snapshot()

    def fake_calls(self):
        return [call for call in self.transport.calls if call[0] == 'fake-mutate']

    def test_three_environment_profiles_complete(self):
        for environment in m.ENVIRONMENTS:
            directory = Path(self.temp.name) / environment
            directory.mkdir(mode=0o700)
            case = scenario(directory, environment)
            with self.subTest(environment=environment):
                report = self.run_case(case, directory=directory)
                self.assertEqual(report['environment'], environment)
                self.assertEqual(report['application_count'], 3)
                self.assertEqual(report['simulated_mutation_count'], 9)
                self.assertFalse(report['prod_qualified'])

    def test_two_pass_root_then_sorted_children_order(self):
        self.run_case()
        operations = [call[1] for call in self.fake_calls()]
        self.assertEqual(operations, [
            'freeze-app-0000', 'freeze-app-0001', 'freeze-app-0002',
            'orphan-app-0000', 'delete-app-0000',
            'orphan-app-0001', 'delete-app-0001',
            'orphan-app-0002', 'delete-app-0002'])

    def test_success_returns_confirmed_first_stage_receipt(self):
        report = self.run_case()
        receipt = report['confirmed_receipt']
        value = json.loads(receipt['raw'])
        self.assertEqual(value, {'step': m.PHASE, 'environment': 'aws-test',
                                 'confirmed': True, 'simulation_only': True})
        self.assertEqual(receipt['sha256'], m.sha(receipt['raw'].encode()))

    def test_fixed_fake_types_only(self):
        class Other(m.FreezeScenarioTransport):
            pass
        with self.assertRaises(RuleViolation):
            self.run_case(transport=Other({}, {}))
        self.assertFalse((self.directory / 'attempt.json').exists())

    def test_explicit_environment_and_main_required(self):
        for environment, main in (('local', MAIN), ('aws-test', 'bad')):
            with self.subTest(environment=environment), self.assertRaises(RuleViolation):
                m.OfflineFreezeAdapter(environment, main, repository_root=ROOT)

    def test_approval_scope_and_digest_drift_stop_before_observation(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('main', 'b' * 40), ('environment', 'aws-dev'),
                           ('phase', 'drain-runtime'), ('simulation_only', False),
                           ('schema', 'live')):
            self.s = copy.deepcopy(saved); self.s['approval'][key] = value
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()
            self.assertEqual(self.transport.calls, [])
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(approval_hash='f' * 64)

    def test_every_artifact_byte_is_pinned(self):
        saved = copy.deepcopy(self.s)
        for key in m.ARTIFACT_KEYS:
            self.s = copy.deepcopy(saved); self.s['artifacts'][key] += b' '
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()
            self.assertEqual(self.transport.calls, [])

    def test_journal_path_substitution_rejected(self):
        other = Path(self.temp.name) / 'other'; other.mkdir(mode=0o700)
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(directory=other)
        self.assertEqual(self.transport.calls, [])

    def test_confirmation_and_inherited_override_rejected(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('AWS_ENVIRONMENT', 'aws-dev'),
                           ('CONFIRM_AWS_TEST_APPLY', 'x'),
                           ('AWS_ENDPOINT_URL', 'fixture'),
                           ('TF_CLI_ARGS', '-x')):
            self.s = copy.deepcopy(saved); self.s['confirmations'][key] = value
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_proof_expiry_and_renewal_rejected(self):
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(samples=(EXPIRES,) * 200)
        self.s['approval']['created_at'] = '2026-09-16T05:01:00Z'
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(samples=('2026-09-16T05:01:00Z',) * 200)

    def test_root_must_be_first_and_children_sorted(self):
        saved = copy.deepcopy(self.s)
        for kind in ('root-second', 'children-reversed', 'duplicate'):
            self.s = copy.deepcopy(saved)
            def change(value):
                if kind == 'root-second':
                    value['applications'][0], value['applications'][1] = value['applications'][1], value['applications'][0]
                elif kind == 'children-reversed':
                    value['applications'][1:] = list(reversed(value['applications'][1:]))
                else:
                    value['applications'].append(copy.deepcopy(value['applications'][1]))
            self.change_scope(change)
            with self.subTest(kind=kind), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_scope_requires_at_least_root_and_child(self):
        self.change_scope(lambda value: value.update(applications=value['applications'][:1]))
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()

    def test_initial_application_must_be_automated_idle_and_not_deleting(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('automated_sync_enabled', False),
                           ('active_operation', True),
                           ('deletion_requested', True)):
            self.s = copy.deepcopy(saved)
            self.change_scope(lambda scope: scope['applications'][0].update({key: value}))
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_unknown_or_missing_initial_finalizer_rejected(self):
        saved = copy.deepcopy(self.s)
        for finalizers in ([], ['unknown.example/finalizer']):
            self.s = copy.deepcopy(saved)
            self.change_scope(lambda scope: scope['applications'][0].update(finalizers=finalizers))
            with self.subTest(finalizers=finalizers), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_uid_resource_version_and_digest_schema_rejected(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('uid', 'bad'), ('resource_version', '0'),
                           ('source_sha256', 'bad'), ('destination_sha256', 'bad')):
            self.s = copy.deepcopy(saved)
            self.change_scope(lambda scope: scope['applications'][0].update({key: value}))
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_pre_and_immediate_inventory_must_match_reviewed_scope(self):
        for label in ('pre', 'immediate'):
            saved = copy.deepcopy(self.s)
            self.change_observation(label, lambda value: value['applications'].pop())
            with self.subTest(label=label), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()
            self.s = saved

    def test_identity_state_inventory_budget_and_freshness_gates(self):
        saved = copy.deepcopy(self.s)
        changes = (
            lambda value: value['identity'].update(account='1' * 12),
            lambda value: value.update(state_sha256='f' * 64),
            lambda value: value.update(inventory_complete=False),
            lambda value: value.update(estimated_total_usd='36.01'),
            lambda value: value.update(observed_at='2026-09-16T04:58:59Z'),
        )
        for index, change in enumerate(changes):
            self.s = copy.deepcopy(saved); self.change_observation('pre', change)
            with self.subTest(index=index), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_active_operation_or_deletion_before_each_call_stops(self):
        saved = copy.deepcopy(self.s)
        for key in ('active_operation', 'deletion_requested'):
            self.s = copy.deepcopy(saved)
            self.change_observation('app-0000-freeze-pre',
                lambda value: value['applications'][0].update({key: True}))
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()
            self.assertEqual(self.fake_calls(), [])

    def test_resource_version_must_change_after_freeze_and_orphan(self):
        saved = copy.deepcopy(self.s)
        for label in ('app-0000-freeze-post', 'app-0000-orphan-post'):
            self.s = copy.deepcopy(saved)
            before_label = label.replace('-post', '-pre')
            before = json.loads(self.s['observations'][before_label])['applications'][0]
            self.change_observation(label,
                lambda value: value['applications'][0].update(resource_version=before['resource_version']))
            with self.subTest(label=label), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_source_destination_or_uid_drift_after_mutation_stops(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('uid', uid(99)), ('source_sha256', 'f' * 64),
                           ('destination_sha256', 'e' * 64)):
            self.s = copy.deepcopy(saved)
            self.change_observation('app-0000-freeze-post',
                lambda row: row['applications'][0].update({key: value}))
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_unrelated_application_drift_during_freeze_stops(self):
        self.change_observation('app-0000-freeze-post',
            lambda value: value['applications'][1].update(resource_version='999'))
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()

    def test_all_applications_must_be_frozen_before_orphan_pass(self):
        self.change_observation('frozen',
            lambda value: value['applications'][-1].update(automated_sync_enabled=True))
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()
        self.assertEqual([call[1] for call in self.fake_calls()],
                         ['freeze-app-0000', 'freeze-app-0001', 'freeze-app-0002'])

    def test_orphan_must_remove_only_known_target_finalizer(self):
        self.change_observation('app-0000-orphan-post',
            lambda value: value['applications'][0].update(finalizers=['resources-finalizer.argocd.argoproj.io']))
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()

    def test_delete_post_must_remove_exact_first_application(self):
        self.change_observation('app-0000-delete-post',
            lambda value: value.update(applications=list(reversed(value['applications']))))
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()

    def test_explicit_false_records_terminal_failure(self):
        self.s['results']['freeze-app-0000'] = raw({'success': False})
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case()
        snapshot = self.snapshot()
        self.assertTrue(snapshot['failed'])
        self.assertEqual(snapshot['operations']['freeze-app-0000'], 'failure')
        self.assertIsNone(snapshot['pending'])

    def test_unknown_or_interrupted_result_preserves_pending(self):
        saved = copy.deepcopy(self.s)
        for kind in ('schema', 'transport'):
            self.s = copy.deepcopy(saved)
            if kind == 'schema':
                self.s['results']['freeze-app-0000'] = raw({})
            with self.subTest(kind=kind), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case(fail_at='freeze-app-0000' if kind == 'transport' else '')
            self.assertEqual(self.snapshot()['pending'], 'freeze-app-0000')
            self.directory = Path(self.temp.name) / ('pending-' + kind)
            self.directory.mkdir(mode=0o700)
            saved = scenario(self.directory)

    def test_existing_success_failure_or_pending_never_repeats(self):
        self.run_case()
        second = m.FreezeScenarioTransport(self.s['observations'], self.s['results'])
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(transport=second)
        self.assertEqual(second.calls[:2], [('observe', 'pre'), ('observe', 'immediate')])
        self.assertFalse(any(call[0] == 'fake-mutate' for call in second.calls))

    def test_clock_expiry_after_intent_preserves_pending_without_fake_call(self):
        samples = [T] * 7 + [EXPIRES] * 200
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(samples=tuple(samples))
        self.assertFalse(self.fake_calls())
        self.assertEqual(self.snapshot()['pending'], 'freeze-app-0000')

    def test_stale_observation_after_intent_preserves_pending(self):
        later = '2026-09-16T05:01:01Z'
        samples = [T] * 7 + [later] * 200
        with self.assertRaises(m.FreezeSimulationStopped):
            self.run_case(samples=tuple(samples))
        self.assertFalse(self.fake_calls())
        self.assertEqual(self.snapshot()['pending'], 'freeze-app-0000')

    def test_final_application_set_and_state_are_exact(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('applications', [app('extra', 9)]),
                           ('active_application_operations', 1),
                           ('state_unchanged', False)):
            self.s = copy.deepcopy(saved)
            self.change_observation('post', lambda row: row.update({key: value}))
            with self.subTest(key=key), self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()

    def test_completion_write_failure_does_not_return_receipt(self):
        with patch.object(AttemptJournal, 'complete', side_effect=OSError('fixture')):
            with self.assertRaises(m.FreezeSimulationStopped):
                self.run_case()
        self.assertFalse(self.snapshot()['complete'])

    def test_failure_report_is_redacted(self):
        self.change_observation('post', lambda value: value.update(state_unchanged=False))
        try:
            self.run_case()
        except m.FreezeSimulationStopped as error:
            text = json.dumps(error.report, sort_keys=True)
            self.assertNotIn('startup-devops-aws-test-root', text)
            self.assertNotIn(str(self.directory), text)
            self.assertNotIn('00000000-', text)

    def test_receipt_helper_rejects_waiting_failed_live_or_wrong_version(self):
        report = self.run_case()
        saved = copy.deepcopy(report)
        for key, value in (('status', 'offline-cleanup-stage-waiting'),
                           ('live_execution_authorized', True),
                           ('version', 'drift'),
                           ('automatic_retry_performed', True)):
            report = copy.deepcopy(saved); report[key] = value
            with self.subTest(key=key), self.assertRaises(RuleViolation):
                m.simulation_receipt(report)

    def test_confirmed_freeze_receipt_is_consumed_by_first_cleanup_stage(self):
        freeze_report = self.run_case()
        next_directory = Path(self.temp.name) / 'next'; next_directory.mkdir(mode=0o700)
        fixture = load_fixture('cleanup_fixture_receipt',
            'test-v0.11.9.3.6.7.7.5-offline-cleanup-adapters.py')
        case = fixture.scenario(next_directory, 'aws-test', 'drain-external-secrets')
        scope = json.loads(case['artifacts']['scope'])
        scope['receipts'] = [freeze_report['confirmed_receipt']]
        case['artifacts']['scope'] = raw(scope)
        case['approval']['hashes'] = {key: cleanup_adapter.sha(value)
                                      for key, value in case['artifacts'].items()}
        approval = raw(case['approval'])
        result = cleanup_adapter.OfflineCleanupAdapter('aws-test',
            'drain-external-secrets', MAIN, repository_root=ROOT).run(
                case['artifacts'], approval, cleanup_adapter.sha(approval),
                journal_directory=next_directory, confirmations=case['confirmations'],
                transport=cleanup_adapter.CleanupScenarioTransport(
                    case['observations'], case['results']),
                clock=m.ScenarioClock((fixture.T,) * 100))
        self.assertEqual(result['status'], 'offline-cleanup-stage-simulation-complete')

    def test_complete_three_environment_eight_stage_receipt_chain(self):
        cleanup_fixture = load_fixture('cleanup_fixture_chain',
            'test-v0.11.9.3.6.7.7.5-offline-cleanup-adapters.py')
        destroy_fixture = load_fixture('destroy_fixture_chain',
            'test-v0.11.9.3.6.7.7.4-offline-destroy-adapters.py')
        matrix = []
        for environment in m.ENVIRONMENTS:
            freeze_directory = Path(self.temp.name) / ('chain-' + environment + '-freeze')
            freeze_directory.mkdir(mode=0o700)
            freeze_case = scenario(freeze_directory, environment)
            report = self.run_case(freeze_case, directory=freeze_directory)
            receipts = [m.simulation_receipt(report)]
            matrix.append((environment, m.PHASE))
            for phase in CLEANUP_STEPS[1:]:
                directory = Path(self.temp.name) / ('chain-' + environment + '-' + phase)
                directory.mkdir(mode=0o700)
                if phase in cleanup_adapter.PHASES:
                    case = cleanup_fixture.scenario(directory, environment, phase)
                    scope = json.loads(case['artifacts']['scope'])
                    scope['receipts'] = copy.deepcopy(receipts)
                    case['artifacts']['scope'] = raw(scope)
                    case['approval']['hashes'] = {key: cleanup_adapter.sha(value)
                                                  for key, value in case['artifacts'].items()}
                    approval = raw(case['approval'])
                    report = cleanup_adapter.OfflineCleanupAdapter(environment, phase,
                        MAIN, repository_root=ROOT).run(case['artifacts'], approval,
                        cleanup_adapter.sha(approval), journal_directory=directory,
                        confirmations=case['confirmations'],
                        transport=cleanup_adapter.CleanupScenarioTransport(
                            case['observations'], case['results']),
                        clock=m.ScenarioClock((cleanup_fixture.T,) * 120))
                else:
                    case = destroy_fixture.scenario(directory, environment, phase)
                    scope = json.loads(case['artifacts']['scope'])
                    scope['receipts'] = copy.deepcopy(receipts)
                    case['artifacts']['scope'] = raw(scope)
                    case['approval']['hashes'] = {key: destroy_adapter.sha(value)
                                                  for key, value in case['artifacts'].items()}
                    approval = raw(case['approval'])
                    report = destroy_adapter.OfflineDestroyAdapter(environment, phase,
                        MAIN, repository_root=ROOT).run(case['artifacts'], approval,
                        destroy_adapter.sha(approval), journal_directory=directory,
                        confirmations=case['confirmations'],
                        transport=destroy_adapter.ScenarioTransport(
                            case['observations'], raw({'success': True})),
                        clock=m.ScenarioClock((destroy_fixture.T,) * 20))
                receipts.append(m.simulation_receipt(report))
                matrix.append((environment, phase))
            self.assertEqual(tuple(row['step'] for row in receipts), CLEANUP_STEPS)
        self.assertEqual(len(matrix), 24)
        self.assertEqual(len(set(matrix)), 24)

    def test_core_ast_has_no_live_or_dynamic_backend_primitive(self):
        tree = ast.parse((ROOT / 'scripts/guarded_freeze_simulation_v6777.py').read_text())
        forbidden_imports = {'boto3', 'botocore', 'subprocess', 'socket', 'urllib',
                             'requests', 'os', 'datetime', 'time'}
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split('.')[0])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr,
                    {'run', 'Popen', 'system', 'getenv', 'now', 'utcnow',
                     'unlink', 'write_text', 'read_text'})
        self.assertFalse(imports & forbidden_imports)


if __name__ == '__main__':
    unittest.main(verbosity=2)
