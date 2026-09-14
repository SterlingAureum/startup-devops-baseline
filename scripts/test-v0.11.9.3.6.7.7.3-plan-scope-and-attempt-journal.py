#!/usr/bin/env python3
"""Offline exact plan fixtures and real Linux journal crash/concurrency tests."""
import ast
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import guarded_plan_rules as g
import guarded_attempt_journal as j
from guarded_runtime_rules import RuleViolation

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('historical_dependency_fixture', ROOT/'scripts/test-v0.11.9.3.6.7.6.4-aws-test-teardown.py')
historical = importlib.util.module_from_spec(spec)
spec.loader.exec_module(historical)
T = '2026-09-14T00:00:00Z'
LATER = '2026-09-14T00:01:00Z'
BINDING = {'environment':'aws-test','phase':'fixture-cleanup','main':'a'*40,
           'inputs_sha256':'b'*64,'state_sha256':'c'*64,'proof_sha256':'d'*64,'scope_sha256':'e'*64}

def fixture():
    state, plan = historical.fixtures()
    state['version'] = 4
    inventory = g.managed_inventory(state)
    reviewed = tuple(inventory[x['address']] for x in plan['resource_changes'])
    return state, plan, reviewed

class PlanTests(unittest.TestCase):
    def gate(self, state, plan, reviewed, final=False, absence=()):
        return g.validate_destroy_plan(plan,state,reviewed,final=final,reviewed_remote_absence=absence)
    def test_historical_fifty_dependency_gate_parity(self):
        state,plan,reviewed=fixture()
        self.assertEqual(self.gate(state,plan,reviewed),historical.m.plan_gate(plan,state,'eks'))
    def test_final_covers_every_current_managed_resource(self):
        state,plan,_=fixture(); inventory=g.managed_inventory(state)
        reviewed=tuple(inventory.values())
        plan['resource_changes']=[{'address':r['address'],'module_address':r['module'],'mode':'managed','type':r['type'],
                                  'change':{'actions':['delete'],'before':{'id':r['id']},'after':None}} for r in reviewed]
        self.assertEqual(self.gate(state,plan,reviewed,True)['managed_delete_count'],55)
    def test_final_subset_rejected(self):
        with self.assertRaises(RuleViolation): self.gate(*fixture(),final=True)
    def test_targeted_subset_retains_unreviewed_state(self):
        state,plan,reviewed=fixture()
        self.assertEqual(len(g.managed_inventory(state)),55)
        self.assertEqual(self.gate(state,plan,reviewed)['managed_delete_count'],50)
    def test_missing_extra_duplicate_changes(self):
        for kind in ('missing','extra','duplicate'):
            state,plan,reviewed=fixture()
            if kind=='missing': plan['resource_changes'].pop()
            elif kind=='extra': plan['resource_changes'].append(copy.deepcopy(plan['resource_changes'][0]))
            else: plan['resource_changes'][1]=copy.deepcopy(plan['resource_changes'][0])
            with self.subTest(kind=kind),self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
    def test_same_type_name_module_index_and_id_substitutions(self):
        for kind in ('address','module_address','type','id','name'):
            state,plan,reviewed=fixture(); item=plan['resource_changes'][0]
            if kind=='id': item['change']['before']={'id':'fixture-other'}
            elif kind=='name': reviewed=(dict(reviewed[0],name='other'),)+reviewed[1:]
            else: item[kind]=item[kind]+'-other'
            with self.subTest(kind=kind),self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
    def test_create_update_replacement_noop_read_data_rejected(self):
        for actions in (['create'],['update'],['delete','create'],['create','delete'],['no-op'],['read']):
            state,plan,reviewed=fixture();plan['resource_changes'][0]['change']['actions']=actions
            with self.subTest(actions=actions),self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
        state,plan,reviewed=fixture();plan['resource_changes'][0]['mode']='data'
        with self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
    def test_after_missing_or_nonnull_rejected(self):
        for kind in ('missing','nonnull'):
            state,plan,reviewed=fixture();change=plan['resource_changes'][0]['change']
            if kind=='missing': del change['after']
            else: change['after']={}
            with self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
    def test_explicit_reviewed_remote_absence(self):
        state,plan,reviewed=fixture(); drift=plan['resource_changes'].pop(0);plan['resource_drift']=[drift]
        gate=self.gate(state,plan,reviewed,absence=(drift['address'],))
        self.assertEqual((gate['managed_delete_count'],gate['reviewed_remote_absence_count']),(49,1))
    def test_unreviewed_unknown_duplicate_or_overlapping_drift(self):
        for kind in ('unreviewed','unknown','duplicate','overlap'):
            state,plan,reviewed=fixture();drift=copy.deepcopy(plan['resource_changes'][0]);plan['resource_drift']=[drift]
            absence=(drift['address'],)
            if kind!='overlap': plan['resource_changes'].pop(0)
            if kind=='unreviewed': absence=()
            elif kind=='unknown': drift['address']='aws_vpc.unreviewed'
            elif kind=='duplicate': plan['resource_drift'].append(copy.deepcopy(drift))
            with self.subTest(kind=kind),self.assertRaises(RuleViolation): self.gate(state,plan,reviewed,absence=absence)
    def test_reviewed_absence_missing_from_plan(self):
        state,plan,reviewed=fixture()
        with self.assertRaises(RuleViolation): self.gate(state,plan,reviewed,absence=(reviewed[0]['address'],))
    def test_invalid_state_schema_id_deposed_and_duplicate(self):
        for kind in ('version','id','deposed','duplicate'):
            state,plan,reviewed=fixture()
            if kind=='version': state['version']=3
            elif kind=='id': state['resources'][0]['instances'][0]['attributes']={}
            elif kind=='deposed': state['resources'][0]['instances'][0]['deposed']='old'
            else: state['resources'].append(copy.deepcopy(state['resources'][0]))
            with self.subTest(kind=kind),self.assertRaises(RuleViolation): self.gate(state,plan,reviewed)
    def test_root_nested_and_indexed_definitions(self):
        state={'version':4,'resources':[{'mode':'managed','type':'aws_iam_role','name':'root','instances':[{'attributes':{'id':'root'}}]},
         {'module':'module.outer[0].module.inner["key"]','mode':'managed','type':'aws_iam_role','name':'nested',
          'instances':[{'index_key':'key','attributes':{'id':'nested'}}]}]}
        rows=tuple(g.managed_inventory(state).values())
        plan={'resource_changes':[{'address':r['address'],'module_address':r['module'],'mode':'managed','type':r['type'],
         'change':{'actions':['delete'],'before':{'id':r['id']},'after':None}} for r in rows]}
        self.assertEqual(self.gate(state,plan,rows,True)['managed_delete_count'],2)
    def test_inputs_immutable_and_errors_redacted(self):
        args=fixture(); saved=copy.deepcopy(args);self.gate(*args);self.assertEqual(args,saved)
        args[1]['resource_changes'][0]['change']['before']['id']='private-value'
        with self.assertRaises(RuleViolation) as e: self.gate(*args)
        self.assertNotIn('private-value',str(e.exception))
    def test_gate_has_no_io_transport_or_clock_imports(self):
        tree=ast.parse((ROOT/'scripts/guarded_plan_rules.py').read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{x.name for n in ast.walk(tree) if isinstance(n,ast.Import) for x in n.names}
        self.assertEqual(imports,{'__future__','json','guarded_runtime_rules'})

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT.parent,prefix='journal-fixture-')
        self.directory=Path(self.temp.name)/'private';self.directory.mkdir(mode=0o700)
        self.handles=[]
    def tearDown(self):
        for h in self.handles:h.close()
        self.temp.cleanup()
    def reserve(self):
        h=j.AttemptJournal.reserve(self.directory,BINDING,T,repository_root=ROOT);self.handles.append(h);return h
    def reopen(self,sha):
        h=j.AttemptJournal.open(self.directory,BINDING,sha,repository_root=ROOT);self.handles.append(h);return h
    def test_exclusive_reservation_and_modes(self):
        h=self.reserve()
        for name in ('attempt.json','events.jsonl','head.json'):self.assertEqual((self.directory/name).stat().st_mode&0o777,0o600)
        with self.assertRaises(RuleViolation):self.reserve()
        self.assertEqual(h.snapshot()['sequence'],0)
    def test_intent_is_durable_before_fake_transport(self):
        h=self.reserve();transport=Mock()
        h.before('delete-one',T)
        transport(self.reopen(h.marker_sha256).snapshot()['pending'])
        transport.assert_called_once_with('delete-one')
    def test_pending_reopen_blocks_repeat_and_next_operation(self):
        h=self.reserve();h.before('delete-one',T);h.close();other=self.reopen(h.marker_sha256)
        for op in ('delete-one','delete-two'):
            with self.assertRaises(RuleViolation):other.before(op,LATER)
        with self.assertRaises(RuleViolation):other.observed_absent('delete-one',LATER)
        with self.assertRaises(RuleViolation):other.complete(('delete-one',),LATER)
    def test_failed_phase_terminal_after_reopen(self):
        h=self.reserve();h.before('delete-one',T);h.failure('delete-one',LATER)
        other=self.reopen(h.marker_sha256);self.assertTrue(other.snapshot()['failed'])
        with self.assertRaises(RuleViolation):other.before('delete-two',LATER)
        with self.assertRaises(RuleViolation):other.complete(('delete-one',),LATER)
    def test_success_cannot_repeat_operation(self):
        h=self.reserve();h.before('delete-one',T);h.success('delete-one',T)
        with self.assertRaises(RuleViolation):h.before('delete-one',LATER)
    def test_two_ordered_operations_and_exact_completion(self):
        h=self.reserve()
        for op in ('delete-one','delete-two'):h.before(op,T);h.success(op,T)
        h.complete(('delete-one','delete-two'),LATER)
        self.assertTrue(self.reopen(h.marker_sha256).snapshot()['complete'])
        with self.assertRaises(RuleViolation):h.before('delete-three',LATER)
    def test_native_observed_absence_skips_transport(self):
        h=self.reserve();transport=Mock();h.observed_absent('delete-one',T);h.complete(('delete-one',),T)
        transport.assert_not_called();self.assertEqual(h.snapshot()['operations'],{'delete-one':'observed-absent'})
    def test_completion_scope_and_outcome_without_intent(self):
        h=self.reserve()
        with self.assertRaises(RuleViolation):h.success('delete-one',T)
        h.observed_absent('delete-one',T)
        for expected in ((),('delete-one','delete-two'),('delete-one','delete-one')):
            with self.assertRaises(RuleViolation):h.complete(expected,T)
    def test_time_regression_rejected(self):
        h=self.reserve();h.before('delete-one',LATER)
        with self.assertRaises(RuleViolation):h.success('delete-one',T)
    def test_binding_and_marker_hash_mismatch(self):
        h=self.reserve()
        for binding,sha in ((dict(BINDING,environment='aws-dev'),h.marker_sha256),(BINDING,'f'*64)):
            with self.assertRaises(RuleViolation):j.AttemptJournal.open(self.directory,binding,sha,repository_root=ROOT)
    def test_marker_only_partial_reservation_preserved(self):
        h=self.reserve();sha=h.marker_sha256;h.close();(self.directory/'head.json').unlink()
        with self.assertRaises(RuleViolation):self.reopen(sha)
        with self.assertRaises(RuleViolation):self.reserve()
        self.assertTrue((self.directory/'attempt.json').exists())
    def test_incomplete_tail_and_full_line_truncation(self):
        h=self.reserve();h.before('delete-one',T);events=self.directory/'events.jsonl';raw=events.read_bytes()
        for changed in (raw[:-1],b''):
            events.write_bytes(changed)
            with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
        self.assertTrue((self.directory/'attempt.json').exists())
    def test_head_bool_and_hash_mismatch_rejected(self):
        h=self.reserve();path=self.directory/'head.json';head=json.loads(path.read_text())
        for changed in (dict(head,sequence=False),dict(head,events_sha256='f'*64)):
            path.write_bytes(j.encode(changed))
            with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
    def test_leftover_head_commit_preserved(self):
        h=self.reserve();path=self.directory/'head-next.json';path.write_bytes(b'partial');path.chmod(0o600)
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
        self.assertEqual(path.read_bytes(),b'partial')
    def test_changed_modes_symlinks_and_hardlinks_rejected(self):
        h=self.reserve();path=self.directory/'events.jsonl';path.chmod(0o644)
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
        path.chmod(0o600);link=self.directory/'extra';os.link(path,link)
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
        link.unlink();path.unlink();path.symlink_to(self.directory/'head.json')
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
    def test_ephemeral_repository_or_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuleViolation):j.AttemptJournal.reserve(Path(tmp),BINDING,T,repository_root=ROOT)
        with self.assertRaises(RuleViolation):j.AttemptJournal.reserve(ROOT,BINDING,T,repository_root=ROOT)
        link=Path(self.temp.name)/'linked';link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(RuleViolation):j.AttemptJournal.reserve(link,BINDING,T,repository_root=ROOT)
    def test_concurrent_reservation_has_one_winner(self):
        def worker(_):
            try:
                h=j.AttemptJournal.reserve(self.directory,BINDING,T,repository_root=ROOT);h.close();return True
            except RuleViolation:return False
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(sum(pool.map(worker,range(4))),1)
    def test_concurrent_intents_have_one_winner(self):
        first=self.reserve();handles=[self.reopen(first.marker_sha256) for _ in range(2)]
        def worker(pair):
            h,op=pair
            try:h.before(op,T);return True
            except RuleViolation:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(worker,zip(handles,('delete-one','delete-two')))),1)
    def test_fsync_failure_blocks_transport_and_reopen(self):
        h=self.reserve();transport=Mock()
        with patch.object(j.os,'fsync',side_effect=OSError('fixture-io')):
            with self.assertRaises(RuleViolation):
                h.before('delete-one',T);transport()
        transport.assert_not_called()
        with self.assertRaises(RuleViolation):h.before('delete-one',LATER)
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
    def test_head_write_failure_preserves_uncertainty(self):
        h=self.reserve();real=j.AttemptJournal._write
        def fail_head(fd,raw):
            if b'events_bytes' in raw:raise OSError('fixture-head-io')
            return real(fd,raw)
        with patch.object(j.AttemptJournal,'_write',side_effect=fail_head):
            with self.assertRaises(RuleViolation):h.before('delete-one',T)
        self.assertTrue((self.directory/'head-next.json').exists())
        with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)
    def test_canonical_duplicate_json_and_chain_drift_rejected(self):
        h=self.reserve();h.before('delete-one',T);path=self.directory/'events.jsonl';event=json.loads(path.read_text())
        samples=[b'{"sequence":1,"sequence":1}\n',j.encode(dict(event,previous_sha256='f'*64)),json.dumps(event).encode()+b'\n']
        for raw in samples:
            path.write_bytes(raw)
            with self.assertRaises(RuleViolation):self.reopen(h.marker_sha256)

if __name__=='__main__':unittest.main(verbosity=2)
