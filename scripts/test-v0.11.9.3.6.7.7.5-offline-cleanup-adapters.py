#!/usr/bin/env python3
"""Fixed-fake ESO/runtime and ENI/SG cleanup composition tests."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import guarded_cleanup_simulation_v6775 as m
from guarded_attempt_journal import AttemptJournal
from guarded_runtime_rules import RuleViolation

ROOT = Path(__file__).resolve().parent.parent
T = '2026-09-15T05:00:00Z'
EXPIRES = '2026-09-15T05:15:00Z'
END = '2026-09-15T07:00:00Z'
MAIN = 'a' * 40
ZERO_COUNTS = {key: 0 for key in m.RUNTIME_KEYS}


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def uid(number):
    return f'00000000-0000-0000-0000-{number:012d}'


def object_row(kind, name, number):
    versions = {'Namespace': 'v1', 'NodePool': 'karpenter.sh/v1',
                'EC2NodeClass': 'karpenter.k8s.aws/v1'}
    finalizers = ['kubernetes'] if kind == 'Namespace' else ['karpenter.sh/termination']
    return {'api_version': versions[kind], 'kind': kind, 'name': name,
            'namespace': '', 'uid': uid(number), 'resource_version': str(100 + number),
            'finalizers': finalizers, 'deletion_requested': False}


def external_secret():
    return {'api_version': 'external-secrets.io/v1', 'kind': 'ExternalSecret',
            'name': 'fixture-secret', 'namespace': 'startup-apps', 'uid': uid(9),
            'resource_version': '109',
            'finalizers': ['externalsecrets.external-secrets.io/externalsecret-cleanup'],
            'deletion_requested': True, 'creation_policy': 'CreateOrMerge',
            'deletion_policy': 'Retain'}


def network_rows(environment):
    suffix = environment.removeprefix('aws-')
    group = {'GroupId': 'sg-a1b2c3', 'OwnerId': '0' * 12, 'VpcId': 'vpc-a1b2c3',
             'GroupName': f'eks-cluster-sg-fixture-{suffix}-1234',
             'Description': 'fixture group', 'IpPermissions': [],
             'IpPermissionsEgress': []}
    interface = {'NetworkInterfaceId': 'eni-a1b2c3', 'OwnerId': '0' * 12,
                 'VpcId': 'vpc-a1b2c3', 'SubnetId': 'subnet-a1b2c3',
                 'Description': 'aws-K8S fixture i-a1b2c3', 'InterfaceType': 'interface',
                 'RequesterManaged': False, 'RequesterId': '', 'Status': 'available',
                 'Attachment': None, 'Association': None,
                 'Groups': [{'GroupId': 'sg-a1b2c3'}]}
    scope = {'environment': environment, 'account': '0' * 12,
             'vpc_id': 'vpc-a1b2c3', 'group_id': 'sg-a1b2c3',
             'cluster': f'fixture-{suffix}', 'subnet_ids': ['subnet-a1b2c3'],
             'instance_ids': ['i-a1b2c3'], 'native_inventory_complete': True,
             'eks_absent': True, 'captured_compute_absent': True,
             'captured_volumes_absent': True, 'load_balancers_absent': True,
             'target_groups_absent': True, 'test_dns_absent': True}
    return interface, group, scope


def cleanup_facts(phase, external_count=0):
    value = {key: True for key in ('scope_verified', 'inventory_complete',
        'applications_frozen', 'eso_ready', 'eso_can_patch', 'scoped_rbac_retained',
        'cleanup_controllers_ready', 'eks_absent', 'captured_compute_absent',
        'captured_volumes_absent', 'load_balancers_absent', 'target_groups_absent',
        'test_dns_absent')}
    value['business_namespace_deletion_requested'] = False
    value.update({key: 0 for key in ('active_application_operations', 'applications',
        'unknown_finalizers', 'business_namespaces', 'nodeclaims', 'persistent_volumes',
        'captured_runtime_compute', 'captured_pv_volumes', 'load_balancers',
        'target_groups', 'test_dns_records', 'nodepools', 'nodeclasses')})
    value['external_secrets'] = external_count
    return value


def scenario(directory, environment='aws-test', phase='drain-external-secrets'):
    inputs = {'environment': environment, 'region': 'us-east-1', 'account': '0' * 12,
              'cluster': 'fixture-' + environment.removeprefix('aws-'),
              'budget_limit_usd': '36.00'}
    state = {'version': 4, 'resources': []}
    receipts = []
    for step in m.CLEANUP_STEPS[:m.CLEANUP_STEPS.index(phase)]:
        text = raw({'step': step, 'environment': environment, 'confirmed': True,
                    'simulation_only': True}).decode()
        receipts.append({'step': step, 'raw': text, 'sha256': m.sha(text.encode())})
    scope = {'environment': environment, 'phase': phase, 'receipts': receipts}
    if phase == 'drain-external-secrets':
        scope['external_secrets'] = []
    elif phase == 'delete-business-namespaces':
        scope['objects'] = [object_row('Namespace', 'startup-apps', 1),
                            object_row('Namespace', 'data-platform', 2)]
    elif phase == 'delete-node-config':
        scope['objects'] = [object_row('NodePool', 'applications', 3),
                            object_row('EC2NodeClass', 'applications', 4)]
    elif phase == 'eni-sg-cleanup':
        interface, group, network = network_rows(environment)
        scope.update({'captured_eni': interface, 'captured_sg': group,
                      'network_scope': network})
    artifacts = {'inputs': raw(inputs), 'scope': raw(scope), 'state': raw(state)}
    approval = {'schema': 'offline-cleanup-approval-v1', 'simulation_only': True,
        'environment': environment, 'phase': phase, 'main': MAIN,
        'hashes': {key: m.sha(value) for key, value in artifacts.items()},
        'journal_directory': str(directory), 'start_utc': T, 'end_utc': END,
        'created_at': T, 'original_created_at': T, 'expires_at': EXPIRES,
        'budget_limit_usd': '36.00'}
    base = {'identity': {key: inputs[key] for key in
            ('environment', 'region', 'account', 'cluster')}, 'main': MAIN,
            'observed_at': T, 'inventory_complete': True,
            'estimated_total_usd': '1.00', 'state_sha256': m.sha(artifacts['state']),
            'cleanup': cleanup_facts(phase)}
    observations = {'pre': copy.deepcopy(base), 'immediate': copy.deepcopy(base)}
    results = {}
    if phase == 'drain-external-secrets':
        observations['pre']['external_secrets'] = []
        observations['immediate']['external_secrets'] = []
        observations['post'] = copy.deepcopy(base) | {'external_secrets': [],
                                                       'state_unchanged': True}
    elif phase == 'drain-runtime':
        observations['pre']['runtime_remaining_counts'] = dict(ZERO_COUNTS)
        observations['immediate']['runtime_remaining_counts'] = dict(ZERO_COUNTS)
        observations['post'] = copy.deepcopy(base) | {
            'runtime_remaining_counts': dict(ZERO_COUNTS), 'state_unchanged': True}
    elif phase in ('delete-business-namespaces', 'delete-node-config'):
        objects = copy.deepcopy(scope['objects'])
        observations['pre']['objects'] = objects
        observations['immediate']['objects'] = objects
        remaining = list(objects)
        for index in range(len(objects)):
            label = str(index).zfill(4)
            observations[f'object-{label}-pre'] = copy.deepcopy(base) | {
                'objects': copy.deepcopy(remaining)}
            remaining = remaining[1:]
            observations[f'object-{label}-post'] = copy.deepcopy(base) | {
                'objects': copy.deepcopy(remaining)}
            results[f'delete-object-{label}'] = raw({'success': True})
        observations['post'] = copy.deepcopy(base) | {'objects': [],
                                                       'state_unchanged': True}
    else:
        interface, group, _ = network_rows(environment)
        observations['pre'].update({'current_eni': interface,
            'interfaces_by_group': [interface], 'group_present': True,
            'current_sg': group, 'groups_in_vpc': [group],
            'interfaces_for_sg': [interface]})
        observations['immediate'] = copy.deepcopy(observations['pre'])
        observations['eni-post'] = copy.deepcopy(base) | {'current_eni': None,
            'interfaces_by_group': [], 'group_present': True, 'current_sg': group,
            'groups_in_vpc': [group], 'interfaces_for_sg': []}
        observations['sg-post'] = copy.deepcopy(base) | {'current_eni': None,
            'interfaces_by_group': [], 'group_present': False, 'current_sg': None,
            'groups_in_vpc': [], 'interfaces_for_sg': []}
        observations['post'] = copy.deepcopy(observations['sg-post']) | {
            'state_unchanged': True}
        results = {'delete-captured-eni': raw({'success': True}),
                   'delete-captured-sg': raw({'success': True})}
    confirmations = {'AWS_ENVIRONMENT': environment,
        'CONFIRM_' + environment.upper().replace('-', '_') + '_OFFLINE_CLEANUP':
        f'simulate-reviewed-{environment}-{phase}-once'}
    return {'environment': environment, 'phase': phase, 'artifacts': artifacts,
            'approval': approval, 'observations': {k: raw(v) for k, v in observations.items()},
            'results': results, 'confirmations': confirmations}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='cleanup-adapter-')
        self.case_id = 0
        self.directory = Path(self.temp.name) / 'journal'
        self.directory.mkdir(mode=0o700)
        self.s = scenario(self.directory)
        self.transport = None

    def tearDown(self):
        self.temp.cleanup()

    def run_case(self, scenario_value=None, *, directory=None, samples=None,
                 fail_at='', transport=None, approval_hash=None):
        s = scenario_value or self.s
        approval = raw(s['approval'])
        self.transport = transport or m.CleanupScenarioTransport(
            s['observations'], s['results'], fail_at=fail_at)
        return m.OfflineCleanupAdapter(s['environment'], s['phase'], MAIN,
            repository_root=ROOT).run(s['artifacts'], approval,
            approval_hash or m.sha(approval), journal_directory=directory or self.directory,
            confirmations=s['confirmations'], transport=self.transport,
            clock=m.ScenarioClock(samples or (T,) * 80))

    def reset(self, phase='drain-external-secrets', environment='aws-test'):
        self.case_id += 1
        directory = Path(self.temp.name) / f'{self.case_id:03d}-{phase}-{environment}'
        directory.mkdir(mode=0o700)
        self.directory = directory
        self.s = scenario(directory, environment, phase)

    def change_observation(self, label, function):
        value = json.loads(self.s['observations'][label])
        function(value)
        self.s['observations'][label] = raw(value)

    def change_artifact(self, key, function):
        value = json.loads(self.s['artifacts'][key])
        function(value)
        self.s['artifacts'][key] = raw(value)

    def refresh(self):
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

    def test_fifteen_environment_phase_combinations(self):
        for environment in ('aws-dev', 'aws-test', 'aws-prod'):
            for phase in m.PHASES:
                self.reset(phase, environment)
                with self.subTest(environment=environment, phase=phase):
                    report = self.run_case()
                    self.assertEqual(report['status'], 'offline-cleanup-stage-simulation-complete')
                    self.assertEqual(report['environment'], environment)
                    self.assertFalse(report['prod_qualified'])
                    self.assertFalse(report['aws_mutation_executed'])

    def test_fixed_fake_types_only(self):
        class Other(m.CleanupScenarioTransport):
            pass
        with self.assertRaises(RuleViolation):
            self.run_case(transport=Other({}, {}))

    def test_explicit_environment_phase_and_main_required(self):
        for environment, phase, main in (('local', m.PHASES[0], MAIN),
                ('aws-test', 'final-delete', MAIN), ('aws-test', m.PHASES[0], 'bad')):
            with self.subTest(environment=environment, phase=phase):
                with self.assertRaises(RuleViolation):
                    m.OfflineCleanupAdapter(environment, phase, main, repository_root=ROOT)

    def test_approval_scope_and_digest_drift_stop_before_observation(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('main', 'b' * 40), ('environment', 'aws-dev'),
                ('phase', 'drain-runtime'), ('simulation_only', False), ('schema', 'live')):
            self.s = copy.deepcopy(saved); self.s['approval'][key] = value
            with self.subTest(key=key), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertEqual(self.transport.calls, [])
        with self.assertRaises(m.CleanupSimulationStopped):
            self.run_case(approval_hash='f' * 64)

    def test_every_artifact_byte_is_pinned(self):
        saved = copy.deepcopy(self.s)
        for key in m.ARTIFACT_KEYS:
            self.s = copy.deepcopy(saved); self.s['artifacts'][key] += b' '
            with self.subTest(key=key), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertEqual(self.transport.calls, [])

    def test_journal_path_substitution_rejected(self):
        other = Path(self.temp.name) / 'other'; other.mkdir(mode=0o700)
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(directory=other)
        self.assertEqual(self.transport.calls, [])

    def test_confirmation_and_inherited_override_rejected(self):
        saved = copy.deepcopy(self.s)
        for key, value in (('AWS_ENVIRONMENT', 'aws-dev'), ('CONFIRM_AWS_TEST_APPLY', 'x'),
                           ('AWS_ENDPOINT_URL', 'fixture'), ('TF_CLI_ARGS', '-x')):
            self.s = copy.deepcopy(saved); self.s['confirmations'][key] = value
            with self.subTest(key=key), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()

    def test_proof_expiry_and_renewal_rejected(self):
        with self.assertRaises(m.CleanupSimulationStopped):
            self.run_case(samples=(EXPIRES,) * 80)
        self.s['approval']['created_at'] = '2026-09-15T05:01:00Z'
        with self.assertRaises(m.CleanupSimulationStopped):
            self.run_case(samples=('2026-09-15T05:01:00Z',) * 80)

    def test_identity_state_inventory_budget_and_freshness_gates(self):
        saved = copy.deepcopy(self.s)
        changes = (('identity', lambda o: o['identity'].update(account='1' * 12)),
                   ('state', lambda o: o.update(state_sha256='f' * 64)),
                   ('inventory', lambda o: o.update(inventory_complete=False)),
                   ('budget', lambda o: o.update(estimated_total_usd='36.01')),
                   ('freshness', lambda o: o.update(observed_at='2026-09-15T04:58:59Z')))
        for name, function in changes:
            self.s = copy.deepcopy(saved); self.change_observation('pre', function)
            with self.subTest(name=name), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertEqual(self.fake_calls(), [])

    def test_receipt_hash_order_and_confirmation_are_exact(self):
        self.reset('delete-business-namespaces')
        saved = copy.deepcopy(self.s)
        for kind in ('hash', 'order', 'confirmed'):
            self.s = copy.deepcopy(saved)
            def change(value):
                if kind == 'hash': value['receipts'][0]['sha256'] = 'f' * 64
                elif kind == 'order': value['receipts'].reverse()
                else:
                    row = value['receipts'][0]; content = json.loads(row['raw'])
                    content['confirmed'] = False; row['raw'] = raw(content).decode()
                    row['sha256'] = m.sha(row['raw'].encode())
            self.change_artifact('scope', change); self.refresh()
            with self.subTest(kind=kind), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()

    def test_external_secret_waits_without_journal_or_fake_call(self):
        item = external_secret()
        self.change_artifact('scope', lambda o: o.update(external_secrets=[item]))
        self.refresh()
        for label in ('pre', 'immediate'):
            self.change_observation(label, lambda o: (o.update(external_secrets=[item]),
                                                      o['cleanup'].update(external_secrets=1)))
        report = self.run_case()
        self.assertEqual(report['status'], 'offline-cleanup-stage-waiting')
        self.assertFalse(report['journal_reserved'])
        self.assertFalse((self.directory / 'attempt.json').exists())
        self.assertEqual(self.fake_calls(), [])

    def test_external_secret_policy_finalizer_and_deletion_are_exact(self):
        saved = external_secret()
        for field, value in (('deletion_requested', False), ('creation_policy', 'Bad'),
                             ('deletion_policy', 'Bad'), ('finalizers', ['unknown'])):
            item = copy.deepcopy(saved); item[field] = value
            self.change_artifact('scope', lambda o, item=item: o.update(external_secrets=[item]))
            self.refresh()
            for label in ('pre', 'immediate'):
                self.change_observation(label, lambda o, item=item: (
                    o.update(external_secrets=[item]), o['cleanup'].update(external_secrets=1)))
            with self.subTest(field=field), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertFalse((self.directory / 'attempt.json').exists())
            self.reset()

    def test_external_secret_requires_eso_health_and_scoped_rbac(self):
        item = external_secret()
        self.change_artifact('scope', lambda o: o.update(external_secrets=[item])); self.refresh()
        for label in ('pre', 'immediate'):
            self.change_observation(label, lambda o: (o.update(external_secrets=[item]),
                o['cleanup'].update(external_secrets=1, eso_can_patch=False)))
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertEqual(self.fake_calls(), [])

    def test_runtime_waits_without_journal(self):
        self.reset('drain-runtime')
        counts = dict(ZERO_COUNTS); counts['nodeclaims'] = 2
        for label in ('pre', 'immediate'):
            self.change_observation(label, lambda o: (o.update(runtime_remaining_counts=counts),
                                                       o['cleanup'].update(nodeclaims=2)))
        report = self.run_case()
        self.assertEqual(report['remaining_count'], 2)
        self.assertFalse((self.directory / 'attempt.json').exists())

    def test_absent_drain_records_no_mutation_completion(self):
        for phase in ('drain-external-secrets', 'drain-runtime'):
            self.reset(phase)
            report = self.run_case()
            self.assertEqual(report['simulated_mutation_count'], 0)
            self.assertEqual(report['observed_absence_count'], 1)
            self.assertTrue(self.snapshot()['complete'])

    def test_namespace_scope_and_kind_are_exact(self):
        self.reset('delete-business-namespaces')
        saved = copy.deepcopy(self.s)
        for kind in ('unknown-name', 'wrong-kind', 'deleting', 'duplicate'):
            self.s = copy.deepcopy(saved)
            def change(o):
                if kind == 'unknown-name': o['objects'][0]['name'] = 'other'
                elif kind == 'wrong-kind': o['objects'][0] = object_row('NodePool', 'applications', 5)
                elif kind == 'deleting': o['objects'][0]['deletion_requested'] = True
                else: o['objects'][1] = copy.deepcopy(o['objects'][0])
            self.change_artifact('scope', change); self.refresh()
            with self.subTest(kind=kind), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()

    def test_node_config_requires_both_exact_kinds(self):
        self.reset('delete-node-config')
        self.change_artifact('scope', lambda o: o['objects'].pop())
        self.refresh()
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()

    def test_unknown_object_finalizer_stops_before_journal(self):
        self.reset('delete-business-namespaces')
        self.change_artifact('scope', lambda o: o['objects'][0].update(finalizers=['unknown']))
        self.refresh()
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertFalse((self.directory / 'attempt.json').exists())

    def test_object_uid_resource_version_and_list_drift_stop(self):
        self.reset('delete-business-namespaces')
        saved = copy.deepcopy(self.s)
        for name, function in (('uid', lambda o: o['objects'][0].update(uid=uid(88))),
                               ('rv', lambda o: o['objects'][0].update(resource_version='999')),
                               ('list', lambda o: o.update(objects=[]))):
            self.s = copy.deepcopy(saved); self.change_observation('immediate', function)
            with self.subTest(name=name), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertEqual(self.fake_calls(), [])

    def test_object_operations_are_ordered_and_journaled(self):
        self.reset('delete-business-namespaces')
        report = self.run_case()
        self.assertEqual(report['simulated_mutation_count'], 2)
        self.assertEqual([c[1] for c in self.fake_calls()],
                         ['delete-object-0000', 'delete-object-0001'])
        self.assertTrue(self.snapshot()['complete'])

    def test_intent_is_durable_before_object_call(self):
        self.reset('delete-business-namespaces')
        original = m.CleanupScenarioTransport.mutate
        def inspect(transport, operation, identity):
            snapshot = self.snapshot()
            self.assertEqual(snapshot['pending'], operation)
            return original(transport, operation, identity)
        with patch.object(m.CleanupScenarioTransport, 'mutate', inspect):
            self.run_case()

    def test_object_explicit_failure_terminal(self):
        self.reset('delete-business-namespaces')
        self.s['results']['delete-object-0000'] = raw({'success': False})
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertTrue(self.snapshot()['failed'])

    def test_object_uncertain_result_or_post_preserves_pending(self):
        for kind in ('result', 'post'):
            self.reset('delete-business-namespaces')
            if kind == 'result': self.s['results']['delete-object-0000'] = raw({'success': 1})
            with self.subTest(kind=kind), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case(fail_at='object-0000-post' if kind == 'post' else '')
            self.assertEqual(self.snapshot()['pending'], 'delete-object-0000')

    def test_second_object_failure_preserves_first_success(self):
        self.reset('delete-business-namespaces')
        self.s['results']['delete-object-0001'] = raw({'success': False})
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        snapshot = self.snapshot()
        self.assertEqual(snapshot['operations']['delete-object-0000'], 'success')
        self.assertEqual(snapshot['operations']['delete-object-0001'], 'failure')

    def test_existing_completed_or_pending_journal_never_repeats(self):
        self.reset('delete-business-namespaces'); self.run_case()
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertEqual(self.fake_calls(), [])
        self.reset('eni-sg-cleanup')
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(fail_at='delete-captured-eni')
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertEqual(self.fake_calls(), [])

    def test_reserve_and_intent_clock_boundaries_stop_calls(self):
        self.reset('delete-business-namespaces')
        for samples in ((T, T, T, T, EXPIRES) + (EXPIRES,) * 75,
                        (T, T, T, T, T, T, EXPIRES) + (EXPIRES,) * 73):
            with self.assertRaises(m.CleanupSimulationStopped): self.run_case(samples=samples)
            self.assertEqual(self.fake_calls(), [])
            self.reset('delete-business-namespaces')

    def test_observation_rechecked_after_intent(self):
        self.reset('delete-business-namespaces')
        later = '2026-09-15T05:01:01Z'
        samples = (T, T, T, T, T, T, T, later) + (later,) * 72
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(samples=samples)
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(self.snapshot()['pending'], 'delete-object-0000')

    def test_post_deadline_prevents_success_completion(self):
        self.reset('delete-business-namespaces')
        samples = (T,) * 9 + ('2026-09-15T07:00:01Z',) * 71
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(samples=samples)
        self.assertFalse(self.snapshot()['complete'])

    def test_read_only_completion_respects_deadline(self):
        self.reset('drain-runtime')
        samples = (T,) * 8 + ('2026-09-15T07:00:01Z',) * 72
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(samples=samples)
        self.assertFalse(self.snapshot()['complete'])

    def test_eni_then_sg_order_and_identity_digests(self):
        self.reset('eni-sg-cleanup')
        report = self.run_case()
        self.assertEqual([call[1] for call in self.fake_calls()],
                         ['delete-captured-eni', 'delete-captured-sg'])
        self.assertEqual(report['simulated_mutation_count'], 2)
        self.assertTrue(self.snapshot()['complete'])

    def test_absent_eni_skips_delete_but_sg_is_checked(self):
        self.reset('eni-sg-cleanup')
        for label in ('pre', 'immediate'):
            self.change_observation(label, lambda o: o.update(
                current_eni=None, interfaces_by_group=[], interfaces_for_sg=[]))
        report = self.run_case()
        self.assertEqual([call[1] for call in self.fake_calls()], ['delete-captured-sg'])
        self.assertEqual(report['simulated_mutation_count'], 1)

    def test_both_network_objects_absent_are_not_deleted(self):
        self.reset('eni-sg-cleanup')
        for label in ('pre', 'immediate'):
            self.change_observation(label, lambda o: o.update(current_eni=None,
                interfaces_by_group=[], group_present=False, current_sg=None,
                groups_in_vpc=[], interfaces_for_sg=[]))
        report = self.run_case()
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(report['simulated_mutation_count'], 0)

    def test_attached_or_identity_drifted_eni_never_calls(self):
        saved = None
        self.reset('eni-sg-cleanup'); saved = copy.deepcopy(self.s)
        for kind in ('attached', 'owner', 'other-group'):
            self.s = copy.deepcopy(saved)
            def change(o):
                if kind == 'attached': o['current_eni']['Attachment'] = {'AttachmentId': 'x'}
                elif kind == 'owner': o['current_eni']['OwnerId'] = '1' * 12
                else: o['interfaces_by_group'] = []
            self.change_observation('immediate', change)
            with self.subTest(kind=kind), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case()
            self.assertEqual(self.fake_calls(), [])

    def test_other_sg_reference_stops_after_eni_success(self):
        self.reset('eni-sg-cleanup')
        def reference(o):
            other = copy.deepcopy(o['current_sg']); other['GroupId'] = 'sg-deadbeef'
            other['GroupName'] = 'other'; other['IpPermissions'] = [{
                'UserIdGroupPairs': [{'GroupId': 'sg-a1b2c3'}]}]
            o['groups_in_vpc'].append(other)
        self.change_observation('eni-post', reference)
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertEqual([call[1] for call in self.fake_calls()], ['delete-captured-eni'])
        self.assertEqual(self.snapshot()['operations']['delete-captured-eni'], 'success')

    def test_eni_or_sg_post_uncertainty_preserves_pending(self):
        for failure, pending in (('eni-post', 'delete-captured-eni'),
                                 ('sg-post', 'delete-captured-sg')):
            self.reset('eni-sg-cleanup')
            with self.subTest(failure=failure), self.assertRaises(m.CleanupSimulationStopped):
                self.run_case(fail_at=failure)
            self.assertEqual(self.snapshot()['pending'], pending)

    def test_network_call_explicit_failure_is_terminal(self):
        self.reset('eni-sg-cleanup')
        self.s['results']['delete-captured-eni'] = raw({'success': False})
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertTrue(self.snapshot()['failed'])

    def test_network_observation_rechecked_after_intent(self):
        self.reset('eni-sg-cleanup')
        later = '2026-09-15T05:01:01Z'
        samples = (T, T, T, T, T, T, later) + (later,) * 73
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case(samples=samples)
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(self.snapshot()['pending'], 'delete-captured-eni')

    def test_final_state_change_prevents_completion(self):
        self.reset('eni-sg-cleanup')
        self.change_observation('post', lambda o: o.update(state_unchanged=False))
        with self.assertRaises(m.CleanupSimulationStopped): self.run_case()
        self.assertFalse(self.snapshot()['complete'])

    def test_completion_write_failure_does_not_report_success(self):
        with patch.object(AttemptJournal, 'complete', side_effect=RuleViolation('fixture')):
            with self.assertRaises(m.CleanupSimulationStopped): self.run_case()

    def test_failures_are_redacted(self):
        self.s['approval']['main'] = 'bad-private-material'
        with self.assertRaises(m.CleanupSimulationStopped) as caught: self.run_case()
        self.assertEqual(str(caught.exception), 'offline-cleanup-simulation-stopped')
        self.assertNotIn('account', json.dumps(caught.exception.report))

    def test_core_ast_has_no_live_or_dynamic_backend_primitive(self):
        path = ROOT / 'scripts/guarded_cleanup_simulation_v6775.py'
        tree = ast.parse(path.read_text())
        forbidden_modules = {'boto3', 'botocore', 'subprocess', 'socket', 'requests',
                             'urllib', 'os', 'sys', 'time', 'datetime'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(item.name not in forbidden_modules for item in node.names))
            if isinstance(node, ast.ImportFrom): self.assertNotIn(node.module, forbidden_modules)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {'exec', 'eval', '__import__', 'open', 'print'})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {'run', 'Popen', 'system', 'getenv',
                                                  'unlink', 'write_text', 'read_text'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
