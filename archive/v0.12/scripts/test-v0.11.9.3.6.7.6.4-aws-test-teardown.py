#!/usr/bin/env python3
"""Offline exact dependency, failure history, saved-clock and one-attempt checks."""
import copy
import contextlib
import io
import sys
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import aws_test_immutable_root as h
spec = importlib.util.spec_from_file_location('dependency_repair', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.6.4-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
C = h.p.load(h.ROOT / m.CONTRACT)

def fixtures():
    resources = []
    changes = []
    for definition in C['allowedDefinitions']:
        module, kind, name, count = (definition[x] for x in ('module', 'type', 'name', 'count'))
        instances = []
        for index in range(count):
            attrs = {'id': 'fixture-' + str(len(changes))}
            instance = {'attributes': attrs}
            if count > 1:
                instance['index_key'] = 'fixture-key-' + str(index)
            instances.append(instance)
            address = '.'.join((module, kind, name)) + ('[' + json.dumps(instance['index_key']) + ']' if count > 1 else '')
            changes.append({'address': address, 'module_address': module, 'mode': 'managed', 'type': kind, 'change': {'actions': ['delete'], 'before': attrs, 'after': None}})
        resources.append({'module': module, 'mode': 'managed', 'type': kind, 'name': name, 'instances': instances})
    # Retained managed resources are deliberately present in state.
    for kind in ('aws_vpc', 'aws_s3_bucket', 'aws_secretsmanager_secret', 'aws_acm_certificate', 'aws_iam_role'):
        resources.append({'module': 'module.retained', 'mode': 'managed', 'type': kind, 'name': 'keep', 'instances': [{'attributes': {'id': 'fixture-retained-' + kind}}]})
    return {'resources': resources}, {'terraform_version': '1.9.0', 'resource_changes': changes}

class DependencyTests(unittest.TestCase):
    def test_exact_fifty_deletes_and_module_counts(self):
        state, plan = fixtures()
        gate = m.plan_gate(plan, state, 'eks')
        self.assertEqual(gate['managed_delete_count'], 50)
        self.assertEqual(gate['drift'], [])
        counts = {x: sum(a.startswith(x + '.') for a in gate['deleted']) for x in C['expectedModuleCounts']}
        self.assertEqual(counts, C['expectedModuleCounts'])

    def test_old_gate_rejects_real_dependency_shape(self):
        state, plan = fixtures()
        with self.assertRaisesRegex(ValueError, 'non-eks-resource'):
            m.m.plan_gate(plan, state, 'eks')

    def test_other_resource_types_and_same_type_substitution_rejected(self):
        for kind in ('aws_vpc', 'aws_s3_bucket', 'aws_secretsmanager_secret', 'aws_acm_certificate', 'aws_iam_role'):
            state, plan = fixtures()
            plan['resource_changes'][0] = {'address': 'module.retained.' + kind + '.keep', 'module_address': 'module.retained', 'mode': 'managed', 'type': kind, 'change': {'actions': ['delete'], 'before': {'id': 'fixture-retained-' + kind}, 'after': None}}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                m.plan_gate(plan, state, 'eks')

    def test_same_type_same_module_unknown_resource_name_rejected(self):
        state, plan = fixtures()
        index = next(i for i, x in enumerate(plan['resource_changes']) if x['type'] == 'aws_iam_policy')
        old = plan['resource_changes'][index]
        replacement = copy.deepcopy(old)
        replacement['address'] = 'module.karpenter.aws_iam_policy.resource_discovery'
        state['resources'].append({'module': 'module.karpenter', 'mode': 'managed', 'type': 'aws_iam_policy', 'name': 'resource_discovery', 'instances': [{'attributes': replacement['change']['before']}]})
        plan['resource_changes'][index] = replacement
        with self.assertRaises(ValueError):
            m.plan_gate(plan, state, 'eks')

    def test_id_index_type_module_after_and_duplicate_rejected(self):
        for field in ('id', 'index', 'type', 'module', 'after', 'duplicate'):
            state, plan = fixtures()
            item = plan['resource_changes'][0]
            if field == 'id':
                item['change']['before'] = {'id': 'other-fixture-id'}
            elif field == 'index':
                item['address'] += '[99]'
            elif field == 'type':
                item['type'] = 'aws_vpc'
            elif field == 'module':
                item['module_address'] = 'module.eks'
            elif field == 'after':
                item['change']['after'] = {}
            else:
                plan['resource_changes'][1] = copy.deepcopy(item)
            with self.subTest(field=field), self.assertRaises(ValueError):
                m.plan_gate(plan, state, 'eks')

    def test_extra_missing_or_read_change_rejected(self):
        for change in ('missing', 'extra', 'read'):
            state, plan = fixtures()
            if change == 'missing':
                plan['resource_changes'].pop()
            elif change == 'extra':
                plan['resource_changes'].append(copy.deepcopy(plan['resource_changes'][0]))
            else:
                plan['resource_changes'][0]['mode'] = 'data'
                plan['resource_changes'][0]['change']['actions'] = ['read']
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.plan_gate(plan, state, 'eks')

    def test_create_update_noop_and_replacement_rejected(self):
        for actions in (['create'], ['update'], ['no-op'], ['delete', 'create'], ['create', 'delete']):
            state, plan = fixtures()
            plan['resource_changes'][0]['change']['actions'] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                m.plan_gate(plan, state, 'eks')

    def test_managed_drift_rejected(self):
        state, plan = fixtures()
        plan['resource_drift'] = [copy.deepcopy(plan['resource_changes'][0])]
        with self.assertRaisesRegex(ValueError, 'managed-drift'):
            m.plan_gate(plan, state, 'eks')

    def test_state_missing_extra_definition_instance_or_deposed_rejected(self):
        for change in ('missing', 'extra-instance', 'deposed', 'idless'):
            state, plan = fixtures()
            if change == 'missing':
                state['resources'].pop(0)
            elif change == 'extra-instance':
                state['resources'][0]['instances'].append({'index_key': 99, 'attributes': {'id': 'fixture-extra'}})
            elif change == 'deposed':
                state['resources'][0]['instances'][0]['deposed'] = 'fixture-deposed'
            else:
                state['resources'][0]['instances'][0]['attributes'] = {}
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.plan_gate(plan, state, 'eks')

    def test_clock_is_not_reset_by_adoption_or_modified_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            binary = folder / 'destroy.tfplan'
            binary.write_bytes(b'fixture-binary')
            binary.chmod(0o600)
            later = h.p.utc('2026-09-13T13:48:00Z')
            os.utime(binary, (later.timestamp(), later.timestamp()))
            with patch.object(h, 'now', return_value=later):
                self.assertEqual(m.original_plan_time(folder, C), '2026-09-13T13:20:04Z')
            with patch.object(h, 'now', return_value=h.p.utc('2026-09-13T13:50:05Z')):
                with self.assertRaisesRegex(ValueError, 'expired-no-auto-replan'):
                    m.original_plan_time(folder, C)

    def test_adoption_candidate_bytes_stop_before_terraform(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            folder = parent / 'old-plan'
            folder.mkdir(mode=0o700)
            binary = folder / 'destroy.tfplan'
            binary.write_bytes(b'changed-fixture-binary')
            binary.chmod(0o600)
            args = SimpleNamespace(plan_directory=folder)
            runner = Mock()
            with patch.object(h.p, 'persistent'):
                with self.assertRaisesRegex(ValueError, 'candidate-bytes'):
                    m.adopt_plan(runner, args, {}, C, C['originalPlanEarliestAtUtc'])
            runner.invoke.assert_not_called()

    def test_phase_flags_and_old_runtime_flags_rejected(self):
        for phase, expected in m.PHASES.items():
            env = {expected[0]: expected[1]} if expected else {}
            m.confirmations(phase, env)
            for key in ('CONFIRM_AWS_TEST_RUNTIME_CLEANUP', 'CONFIRM_AWS_TEST_RUNTIME_RESUME', 'CONFIRM_AWS_TEST_REMAINING_RUNTIME', 'TF_VAR_environment'):
                with self.subTest(phase=phase, key=key), self.assertRaises(ValueError):
                    m.confirmations(phase, {**env, key: 'old'})
            if expected:
                with self.assertRaises(ValueError):
                    m.confirmations(phase, {})

    def test_old_window_plan_proof_rejected(self):
        with patch.object(m, 'window_digest', return_value='new-window'):
            with self.assertRaises(ValueError):
                m.require_window({'window_contract_sha256': C['originalWindowDigest']})

    def test_failed_gate_label_and_fresh_plan_is_single_operation(self):
        state, plan = fixtures()
        plan['resource_changes'].pop()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            lock = folder / '.terraform.lock.hcl'
            lock.write_text('fixture-lock')
            binary = folder / 'destroy.tfplan'
            binary.write_bytes(b'fixture-saved')
            runner = Mock(output=folder)
            runner.state_hash = 'fixture-state'
            def invoke(label, command, **kwargs):
                return {'terraform-version': {'terraform_version': '1.9.0'}, 'terraform-workspace': b'default', 'terraform-init': b'fixture-init', 'terraform-plan': b'fixture-plan', 'terraform-show-json': plan, 'terraform-show-text': b'fixture-text'}[label]
            runner.invoke.side_effect = invoke
            args = SimpleNamespace(output_directory=folder)
            with patch.object(m, 'TF', folder), patch.object(m, 'state', return_value=state):
                with self.assertRaises(ValueError):
                    m.make_plan(runner, args, {'management_cidr': 'fixture-cidr'}, 'eks')
            self.assertEqual(runner.stage, 'machine-plan-gate')
            self.assertEqual(sum(x.args[0] == 'terraform-plan' for x in runner.invoke.call_args_list), 1)
            self.assertFalse((folder / 'plan-proof.json').exists())

    def test_final_gate_still_accounts_for_all_remaining_managed_state(self):
        state, plan = fixtures()
        with self.assertRaises(ValueError):
            m.plan_gate(plan, state, 'final')
        # A final plan can delete exactly all managed state, with original ID binding.
        for res in state['resources'][len(C['allowedDefinitions']):]:
            attrs = res['instances'][0]['attributes']
            plan['resource_changes'].append({'mode': 'managed', 'type': res['type'], 'address': res['module'] + '.' + res['type'] + '.' + res['name'], 'change': {'actions': ['delete'], 'before': attrs, 'after': None}})
        self.assertEqual(m.plan_gate(plan, state, 'final')['managed_delete_count'], 55)

    def test_adoption_roundtrip_preserves_bytes_clock_and_requires_review(self):
        state, plan = fixtures()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            source, dest, workspace, tf = [parent / x for x in ('old', 'new', 'workspace', 'tf')]
            for x in (source, dest, workspace, tf):
                x.mkdir(mode=0o700)
            def put(path, raw):
                path.write_bytes(raw)
                path.chmod(0o600)
            put(source / 'destroy.tfplan', b'fixture-binary')
            put(source / 'destroy-plan.json', (json.dumps(plan, sort_keys=True, indent=2) + '\n').encode())
            put(source / 'destroy-plan.txt', b'fixture-text')
            put(source / 'state-before.tfstate', b'fixture-state')
            put(workspace / 'runtime-record.json', b'{}\n')
            (tf / '.terraform.lock.hcl').write_text('fixture-lock')
            cfg = copy.deepcopy(C)
            cfg['existingCandidate'] = dict(binaryDigest=h.p.digest(source / 'destroy.tfplan'), jsonDigest=h.p.digest(source / 'destroy-plan.json'), textDigest=h.p.digest(source / 'destroy-plan.txt'))
            cfg['stateSha256'] = h.p.digest(source / 'state-before.tfstate')
            now = h.p.utc('2026-09-13T13:40:00Z')
            os.utime(source / 'destroy.tfplan', (now.timestamp(), now.timestamp()))
            args = SimpleNamespace(plan_directory=source, output_directory=dest, workspace=workspace, inputs=source / 'state-before.tfstate', expected_main='fixture-main')
            runner = Mock(state_hash=cfg['stateSha256'])
            replies = {'terraform-version': {'terraform_version': '1.9.0'}, 'terraform-workspace': b'default', 'original-saved-plan-show-json': plan, 'original-saved-plan-show-text': b'fixture-text'}
            runner.invoke.side_effect = lambda label, command, **kwargs: replies[label]
            with patch.object(h.p, 'persistent'), patch.object(h, 'now', return_value=now), patch.object(m, 'TF', tf), patch.object(m, 'state', return_value=state), patch.object(m, 'runtime_absence'), patch.object(m, 'cloud_scope'):
                result = m.adopt_plan(runner, args, {}, cfg, cfg['originalPlanEarliestAtUtc'])
            proof = json.loads((dest / 'plan-proof.json').read_text())
            self.assertEqual(proof['created_at_utc'], cfg['originalPlanEarliestAtUtc'])
            self.assertFalse(proof['human_reviewed'])
            self.assertFalse(proof['original_plan_clock_reset'])
            self.assertFalse(result['terraform_apply_executed'])
            for name in ('destroy.tfplan', 'destroy-plan.json', 'destroy-plan.txt'):
                self.assertEqual((source / name).read_bytes(), (dest / name).read_bytes())
            commands = [x.args[1] for x in runner.invoke.call_args_list]
            self.assertFalse(any(token in ('init', 'plan', 'apply', 'destroy') for command in commands for token in command))

    def test_driver_expired_adoption_stops_before_runner_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            source = root / 'old'
            source.mkdir(mode=0o700)
            binary = source / 'destroy.tfplan'
            binary.write_bytes(b'fixture-binary')
            binary.chmod(0o600)
            now = h.p.utc('2026-09-13T14:00:00Z')
            os.utime(binary, (now.timestamp(), now.timestamp()))
            args = ['entry', 'adopt-eks', '--inputs', str(root / 'inputs.json'), '--workspace', str(root / 'workspace'), '--output-directory', str(root / 'output'), '--expected-main', 'fixture-main', '--plan-directory', str(source)]
            inputs = {'aws_account_id': 'fixture-owner', 'management_cidr': 'fixture-cidr', 'kubeconfig_path': 'fixture-config', 'recovery_summary_path': 'fixture-summary', 'old_temporary_evidence_lost': True}
            config = copy.deepcopy(C)
            config['recovery'] = {}
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {}, clear=True))
                stack.enter_context(patch.object(sys, 'argv', args))
                for owner, key, value in ((m, 'source_checks', config), (m.m.m, 'projection', {}), (h.p, 'exact_main', None), (m, 'checked', inputs), (h.p, 'digest', config['stateSha256']), (h, 'now', now)):
                    stack.enter_context(patch.object(owner, key, return_value=value))
                runner = stack.enter_context(patch.object(m, 'Runner'))
                history = stack.enter_context(patch.object(m, 'prior_history'))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                status = m.main()
            self.assertEqual(status, 1)
            runner.assert_not_called()
            history.assert_not_called()
            self.assertFalse((root / 'workspace').exists())
            self.assertFalse((root / 'output').exists())

    def test_final_inventory_change_prevents_apply_with_new_entry(self):
        proof = {'stage': 'final', 'main': 'fixture-main', 'human_reviewed': True, 'inputs_sha256': 'fixture-hash', 'state_sha256': 'fixture-hash', 'runtime_record_sha256': 'fixture-hash', 'created_at_utc': h.p.timestamp(), 'terraform_version': '1.9.0', 'provider_lock_sha256': 'fixture-hash', 'gate': {}, 'backup_inventory_digest': 'old', 'container_inventory_digest': 'same'}
        proof.update({key: 'fixture-hash' for key in ('binary_sha256', 'json_sha256', 'text_sha256')})
        args = SimpleNamespace(proof=Path('/fixture/proof.json'), expected_proof_sha256='fixture-hash', expected_main='fixture-main', inputs=Path('/fixture/inputs.json'), workspace=Path('/fixture/workspace'))
        runner = Mock(state_hash='fixture-hash')
        runner.invoke.side_effect = lambda label, command, **kwargs: {'terraform_version': '1.9.0'} if label == 'terraform-version-before-apply' else b'default' if label == 'terraform-workspace-before-apply' else {}
        with patch.object(h, 'read_private', return_value=proof), patch.object(m, 'require_window'), patch.object(h.p, 'digest', return_value='fixture-hash'), patch.object(h.p, 'private'), patch.object(m, 'state', return_value={'resources': []}), patch.object(m, 'plan_gate', return_value={}), patch.object(m, 'final_inventory', return_value={'backup_inventory_digest': 'changed', 'container_inventory_digest': 'same'}), patch.object(h.p, 'write') as write:
            with self.assertRaises(ValueError):
                m.apply_plan(runner, args, {}, 'final')
            write.assert_not_called()
        self.assertFalse(any('apply' in call.args[1] for call in runner.invoke.call_args_list))

if __name__ == '__main__':
    unittest.main()
