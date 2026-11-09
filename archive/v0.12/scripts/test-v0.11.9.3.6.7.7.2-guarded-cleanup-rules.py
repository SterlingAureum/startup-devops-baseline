#!/usr/bin/env python3
"""Dependency/ownership/once-only decision tests, with no service transport."""
import ast
import copy
from pathlib import Path
import unittest
import guarded_cleanup_rules as rules


def scope(environment='test'):
    return {'environment':'aws-'+environment,'account':'0'*12,'vpc_id':'vpc-abc',
        'group_id':'sg-abc','cluster':'fixture-'+environment,'subnet_ids':('subnet-abc',),
        'instance_ids':('i-abc',),'native_inventory_complete':True,'eks_absent':True,
        'captured_compute_absent':True,'captured_volumes_absent':True,'load_balancers_absent':True,
        'target_groups_absent':True,'test_dns_absent':True}


def eni():
    return {'NetworkInterfaceId':'eni-abc','OwnerId':'0'*12,'VpcId':'vpc-abc',
        'SubnetId':'subnet-abc','Description':'aws-K8S-i-abc','InterfaceType':'interface',
        'RequesterManaged':False,'Status':'available','Groups':[{'GroupId':'sg-abc'}]}


def group(environment='test'):
    return {'GroupId':'sg-abc','OwnerId':'0'*12,'VpcId':'vpc-abc',
        'GroupName':'eks-cluster-sg-fixture-'+environment+'-captured','Description':'fixture',
        'IpPermissions':[],'IpPermissionsEgress':[]}


def observation():
    return {'scope_verified':True,'inventory_complete':True,'applications_frozen':True,
        'active_application_operations':0,'applications':0,'unknown_finalizers':0,
        'external_secrets':0,'eso_ready':True,'eso_can_patch':True,'scoped_rbac_retained':True,
        'business_namespace_deletion_requested':False,'business_namespaces':0,
        'cleanup_controllers_ready':True,'nodeclaims':0,'persistent_volumes':0,
        'captured_runtime_compute':0,'captured_pv_volumes':0,'load_balancers':0,
        'target_groups':0,'test_dns_records':0,'nodepools':0,'nodeclasses':0,
        'eks_absent':True,'captured_compute_absent':True,'captured_volumes_absent':True,
        'load_balancers_absent':True,'target_groups_absent':True,'test_dns_absent':True,
        'captured_eni_absent':True,'captured_sg_absent':True}


class DependencyTests(unittest.TestCase):
    def check(self, step, value=None):
        index=rules.CLEANUP_STEPS.index(step)
        return rules.validate_cleanup_step(rules.CLEANUP_STEPS[:index],step,value or observation())

    def test_all_steps_follow_confirmed_receipt_order(self):
        for step in rules.CLEANUP_STEPS:
            with self.subTest(step=step):self.assertEqual(self.check(step),step)

    def test_skip_repeat_duplicate_and_unknown_steps_stop(self):
        for done,step in (((),'eks-delete'),(('freeze-applications',),'freeze-applications'),
            (('freeze-applications','freeze-applications'),'drain-external-secrets'),
            (rules.CLEANUP_STEPS,'final-delete'),((),'force-finalizers')):
            with self.subTest(done=done,step=step),self.assertRaises(rules.RuleViolation):
                rules.validate_cleanup_step(done,step,observation())

    def test_eso_ready_without_scoped_patch_permission_replays_incident_stop(self):
        value=observation();value.update(external_secrets=1,eso_can_patch=False,scoped_rbac_retained=False)
        with self.assertRaises(rules.RuleViolation):self.check('drain-external-secrets',value)

    def test_retained_eso_permissions_allow_drain_before_namespace_deletion(self):
        value=observation();value['external_secrets']=1
        self.check('drain-external-secrets',value)
        with self.assertRaisesRegex(rules.RuleViolation,'external-secret-drain-incomplete'):
            self.check('delete-business-namespaces',value)
        value['external_secrets']=0
        self.check('delete-business-namespaces',value)

    def test_deletion_requested_or_lost_controller_stops_drain(self):
        for key,value in (('business_namespace_deletion_requested',True),('eso_ready',False),
                          ('scoped_rbac_retained',False),('eso_can_patch',False)):
            x=observation();x['external_secrets']=1;x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.check('drain-external-secrets',x)

    def test_unknown_finalizers_stop_without_force_path(self):
        for step in ('drain-external-secrets','delete-business-namespaces'):
            x=observation();x['unknown_finalizers']=1
            with self.subTest(step=step),self.assertRaises(rules.RuleViolation):self.check(step,x)

    def test_applications_and_active_operations_prevent_downstream_delete(self):
        for key,value in (('applications',1),('active_application_operations',1),('applications_frozen',False)):
            x=observation();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.check('delete-business-namespaces',x)

    def test_remaining_namespaces_or_unready_cleanup_controllers_block_runtime(self):
        for key,value in (('business_namespaces',1),('cleanup_controllers_ready',False)):
            x=observation();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.check('drain-runtime',x)

    def test_runtime_dependencies_block_config_and_eks_deletion(self):
        for key in ('nodeclaims','persistent_volumes','captured_runtime_compute','captured_pv_volumes',
                    'load_balancers','target_groups','test_dns_records'):
            x=observation();x[key]=1
            for step in ('delete-node-config','eks-delete'):
                with self.subTest(key=key,step=step),self.assertRaises(rules.RuleViolation):self.check(step,x)

    def test_node_configs_and_orphan_interfaces_block_later_stages(self):
        for key in ('nodepools','nodeclasses'):
            x=observation();x[key]=1
            with self.assertRaises(rules.RuleViolation):self.check('eks-delete',x)
        for key in ('captured_eni_absent','captured_sg_absent','eks_absent'):
            x=observation();x[key]=False
            with self.assertRaises(rules.RuleViolation):self.check('final-delete',x)

    def test_missing_ambiguous_or_incomplete_observation_stops(self):
        for key,value in (('inventory_complete',False),('scope_verified',1),('external_secrets',True),
                          ('external_secrets',-1),('external_secrets',None)):
            x=observation();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.check('drain-external-secrets',x)


class ENITests(unittest.TestCase):
    def decide(self,current=None,**kwargs):
        current=eni() if current is None else current
        return rules.eni_decision(eni(),current,[current],scope(),attempted=False,group_present=True,**kwargs)

    def test_captured_available_unattached_interface_allows_once_decision(self):
        self.assertEqual(self.decide(),'delete-once')

    def test_id_owner_network_type_requester_or_description_drift_rejected(self):
        for key,value in (('NetworkInterfaceId','eni-def'),('OwnerId','1'*12),('VpcId','vpc-def'),
            ('SubnetId','subnet-def'),('InterfaceType','trunk'),('RequesterManaged',True),
            ('RequesterId','changed'),('Description','aws-K8S-i-abcdef')):
            x=eni();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.decide(x)

    def test_attachment_association_and_unavailable_status_block_deletion(self):
        for key,value in (('Attachment',{'InstanceId':'i-abc'}),('Association',{'PublicIp':'fixture'}),
                          ('Attachment',{}),('Association',{}),('Status','in-use')):
            x=eni();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):self.decide(x)

    def test_group_query_disagreement_additional_or_duplicate_groups_block(self):
        for rows in ([],[eni(),eni()]):
            with self.assertRaises(rules.RuleViolation):rules.eni_decision(eni(),eni(),rows,scope(),attempted=False,group_present=True)
        for groups in ([{'GroupId':'sg-def'}],[{'GroupId':'sg-abc'},{'GroupId':'sg-abc'}]):
            x=eni();x['Groups']=groups
            with self.assertRaises(rules.RuleViolation):self.decide(x)

    def test_absent_interface_skips_deletion_but_other_interface_cannot_hide(self):
        self.assertEqual(rules.eni_decision(eni(),None,[],scope(),attempted=True,group_present=True),'confirmed-absent')
        with self.assertRaises(rules.RuleViolation):rules.eni_decision(eni(),None,[eni()],scope(),attempted=False,group_present=True)

    def test_failed_or_interrupted_attempt_is_never_repeated(self):
        with self.assertRaisesRegex(rules.RuleViolation,'interface-attempt-already-consumed'):
            rules.eni_decision(eni(),eni(),[eni()],scope(),attempted=True,group_present=True)

    def test_missing_group_or_native_absence_proof_blocks(self):
        with self.assertRaises(rules.RuleViolation):rules.eni_decision(eni(),eni(),[eni()],scope(),attempted=False,group_present=False)
        for key in ('native_inventory_complete','eks_absent','captured_compute_absent','captured_volumes_absent',
                    'load_balancers_absent','target_groups_absent','test_dns_absent'):
            x=scope();x[key]=False
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):
                rules.eni_decision(eni(),eni(),[eni()],x,attempted=False,group_present=True)


class SGTests(unittest.TestCase):
    def test_exact_unreferenced_interface_free_group_allows_once(self):
        self.assertEqual(rules.sg_decision(group(),group(),[group()],[],scope(),attempted=False),'delete-once')

    def test_attached_interface_or_any_other_group_reference_blocks(self):
        with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),group(),[group()],[eni()],scope(),attempted=False)
        for key in ('IpPermissions','IpPermissionsEgress'):
            other=group();other['GroupId']='sg-def';other[key]=[{'UserIdGroupPairs':[{'GroupId':'sg-abc'}]}]
            with self.subTest(key=key),self.assertRaisesRegex(rules.RuleViolation,'other-group-reference'):
                rules.sg_decision(group(),group(),[group(),other],[],scope(),attempted=False)

    def test_self_reference_is_not_an_external_reference(self):
        x=group();x['IpPermissions']=[{'UserIdGroupPairs':[{'GroupId':'sg-abc'}]}]
        self.assertEqual(rules.sg_decision(x,x,[x],[],scope(),attempted=False),'delete-once')

    def test_identity_rules_or_inventory_drift_blocks(self):
        for key,value in (('GroupId','sg-def'),('OwnerId','1'*12),('VpcId','vpc-def'),('GroupName','other'),
                          ('Description','changed'),('IpPermissionsEgress',[{'IpRanges':[]}])):
            x=group();x[key]=value
            with self.subTest(key=key),self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),x,[x],[],scope(),attempted=False)
        for rows in ([],[group(),group()]):
            with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),group(),rows,[],scope(),attempted=False)

    def test_absent_group_skips_deletion_with_fresh_absence_and_no_interfaces(self):
        self.assertEqual(rules.sg_decision(group(),None,[],[],scope(),attempted=True),'confirmed-absent')
        with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),None,[group()],[],scope(),attempted=False)
        with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),None,[],[eni()],scope(),attempted=False)

    def test_consumed_group_attempt_blocks_repeat_even_after_eni_absence(self):
        with self.assertRaisesRegex(rules.RuleViolation,'group-attempt-already-consumed'):
            rules.sg_decision(group(),group(),[group()],[],scope(),attempted=True)

    def test_bad_reference_schema_and_cross_vpc_inventory_stop(self):
        for value in (None,[None],[{'UserIdGroupPairs':None}],[{'UserIdGroupPairs':[{}]}]):
            x=group();x['IpPermissions']=value
            with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),x,[x],[],scope(),attempted=False)
        x=group();x['VpcId']='vpc-def'
        with self.assertRaises(rules.RuleViolation):rules.sg_decision(group(),group(),[group(),x],[],scope(),attempted=False)


class SharedBoundaryTests(unittest.TestCase):
    def test_explicit_dev_test_prod_scopes_use_same_pure_rules(self):
        for env in ('dev','test','prod'):
            with self.subTest(env=env):
                self.assertEqual(rules.eni_decision(eni(),eni(),[eni()],scope(env),attempted=False,group_present=True),'delete-once')
                self.assertEqual(rules.sg_decision(group(env),group(env),[group(env)],[],scope(env),attempted=False),'delete-once')
        x=scope('prod');x['cluster']='fixture-test'
        with self.assertRaises(rules.RuleViolation):rules.eni_decision(eni(),eni(),[eni()],x,attempted=False,group_present=True)

    def test_inputs_remain_unchanged_and_errors_are_redacted(self):
        x=eni();s=scope();saved=copy.deepcopy((x,s))
        rules.eni_decision(x,x,[x],s,attempted=False,group_present=True)
        self.assertEqual((x,s),saved)
        x['Description']='private-raw-value'
        with self.assertRaises(rules.RuleViolation) as error:rules.eni_decision(eni(),x,[x],s,attempted=False,group_present=True)
        self.assertNotIn('private-raw-value',str(error.exception))

    def test_module_is_pure_and_has_no_force_or_detach_operation(self):
        tree=ast.parse((Path(__file__).parent/'guarded_cleanup_rules.py').read_text())
        allowed={'__future__','re','guarded_runtime_rules'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):self.assertTrue(all(n.name in allowed for n in node.names))
            if isinstance(node,ast.ImportFrom):self.assertIn(node.module,allowed)
            if isinstance(node,ast.Call):
                if isinstance(node.func,ast.Name):self.assertNotIn(node.func.id,{'open','exec','eval','__import__','print'})
                if isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,{'now','utcnow','run','Popen','write_text','read_text','getenv'})


if __name__ == '__main__':
    unittest.main()
