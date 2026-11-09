#!/usr/bin/env python3
"""Offline partial-state, identity, raw DELETE and plan inventory regression gates."""
import copy
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, create_autospec

import aws_test_immutable_root as h
spec = importlib.util.spec_from_file_location('remaining', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.6.3-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def record():
    return {'account': 'fixture-owner', 'management_cidr': 'fixture-cidr', 'cluster_sg': 'fixture-sg', 'zone': 'fixture-zone',
            'outputs': {'vpc_id': 'fixture-vpc'}, 'instance_ids': ['system-' + str(i) for i in range(4)] + ['new-' + str(i) for i in range(4)],
            'new_instance_ids': ['new-' + str(i) for i in range(4)], 'disk_ids': ['disk-' + str(i) for i in range(13)],
            'nodepools': {'application-ondemand': {'limits': {'cpu': '4'}}, 'database-ondemand': {'limits': {'cpu': '6'}}},
            'nodeclasses': {name: {'role': 'fixture-role'} for name in ('application', 'application-fis', 'database')},
            'remnant_uids': {'nodepools': {'application-ondemand': 'pool-app', 'database-ondemand': 'pool-db'},
                            'nodeclasses': {name: 'class-' + name for name in ('application', 'application-fis', 'database')}}}

def object_for(value, label, name):
    return {'apiVersion': 'karpenter.sh/v1' if label == 'nodepools' else 'karpenter.k8s.aws/v1',
            'kind': 'NodePool' if label == 'nodepools' else 'EC2NodeClass',
            'metadata': {'name': name, 'uid': value['remnant_uids'][label][name], 'resourceVersion': '77'},
            'spec': value[label][name]}

def cloud_responses(value, eks=True):
    cluster = {'status': 'ACTIVE', 'endpoint': 'fixture-endpoint', 'resourcesVpcConfig': {'vpcId': 'fixture-vpc', 'clusterSecurityGroupId': 'fixture-sg', 'endpointPublicAccess': True, 'endpointPrivateAccess': True, 'publicAccessCidrs': ['fixture-cidr']}}
    instances = [{'InstanceId': 'system-' + str(i), 'State': {'Name': 'running'}, 'InstanceType': 't3.medium',
                  'Tags': [{'Key': 'aws:autoscaling:groupName', 'Value': 'fixture-asg'}], 'RootDeviceName': '/dev/root',
                  'BlockDeviceMappings': [{'DeviceName': '/dev/root', 'Ebs': {'VolumeId': 'disk-' + str(i), 'DeleteOnTermination': True}}]} for i in range(4)] if eks else []
    volumes = [{'VolumeId': 'disk-' + str(i), 'Size': 30, 'VolumeType': 'gp3', 'Iops': 3000, 'Throughput': 125,
                'State': 'in-use', 'Attachments': [{'InstanceId': 'system-' + str(i)}]} for i in range(4)] if eks else []
    return {'remaining-eks-inventory': {'clusters': [h.p.CLUSTER] if eks else []}, 'remaining-eks-network': {'cluster': cluster},
            'remaining-kube-auth': {}, 'remaining-compute': {'Reservations': [{'Instances': instances}]},
            'remaining-captured-disks': {'Volumes': volumes}, 'remaining-system-disk-inventory': {'Volumes': volumes},
            'remaining-describe-load-balancers': {'LoadBalancers': []}, 'remaining-describe-target-groups': {'TargetGroups': []},
            'remaining-dns': {'ResourceRecordSets': []}}

class RemainingTests(unittest.TestCase):
    def test_only_current_phase_confirmation(self):
        for phase, expected in m.PHASES.items():
            env = {expected[0]: expected[1]} if expected else {}
            m.confirmations(phase, env)
            for forbidden in ('CONFIRM_AWS_TEST_RUNTIME_CLEANUP', 'CONFIRM_AWS_TEST_RUNTIME_RESUME', 'TF_VAR_environment'):
                with self.assertRaises(ValueError):
                    m.confirmations(phase, {**env, forbidden: 'old'})
            if expected:
                with self.assertRaises(ValueError):
                    m.confirmations(phase, {})

    def test_old_window_proof_rejected(self):
        with patch.object(m, 'window_digest', return_value='new-window'):
            with self.assertRaises(ValueError):
                m.require_window({'window_contract_sha256': 'old-window'})

    def test_exactly_five_conditional_config_deletes(self):
        value = record()
        with tempfile.TemporaryDirectory() as directory:
            runner = Mock(output=Path(directory), kube=['fixture-kubectl'])
            def get(label, kind, name, *args, **kwargs):
                if not name:
                    return {'items': []}
                category = 'nodepools' if kind == 'nodepool' else 'nodeclasses'
                return object_for(value, category, name)
            runner.get.side_effect = get
            runner.wait.side_effect = lambda label, read, predicate: self.assertTrue(predicate(read()))
            m.configuration_cleanup(runner, value)
            self.assertEqual(runner.invoke.call_count, 5)
            for call in runner.invoke.call_args_list:
                command = call.args[1]
                self.assertIn('delete', command)
                self.assertTrue(any(x.startswith('--raw=/apis/karpenter') for x in command))
                body = json.loads(Path(command[command.index('-f') + 1]).read_text())
                self.assertEqual(body['propagationPolicy'], 'Background')
                self.assertEqual(body['preconditions']['resourceVersion'], '77')
                self.assertIn('uid', body['preconditions'])
                self.assertNotIn('--force', command)
                self.assertTrue(call.kwargs['mutation'])

    def test_recreated_or_changed_config_never_deleted(self):
        for field in ('uid', 'spec', 'deletionTimestamp', 'apiVersion'):
            value = record()
            with tempfile.TemporaryDirectory() as directory:
                runner = Mock(output=Path(directory), kube=['fixture-kubectl'])
                current = object_for(value, 'nodepools', 'application-ondemand')
                if field == 'spec':
                    current['spec'] = {'different': True}
                elif field == 'apiVersion':
                    current[field] = 'unexpected/v1'
                else:
                    current['metadata'][field] = 'changed'
                runner.get.return_value = current
                with self.assertRaises(ValueError):
                    m.configuration_cleanup(runner, value)
                runner.invoke.assert_not_called()

    def test_failed_delete_has_no_second_request(self):
        value = record()
        with tempfile.TemporaryDirectory() as directory:
            runner = Mock(output=Path(directory), kube=['fixture-kubectl'])
            runner.get.return_value = object_for(value, 'nodepools', 'application-ondemand')
            runner.invoke.side_effect = ValueError('failed-delete')
            with self.assertRaises(ValueError):
                m.configuration_cleanup(runner, value)
            self.assertEqual(runner.invoke.call_count, 1)

    def test_actual_kubectl_sends_uid_version_delete_options(self):
        cli = shutil.which('kubectl')
        if not cli:
            self.skipTest('kubectl unavailable; behavioral checks remain required')
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_DELETE(self):
                if self.headers.get('Transfer-Encoding') == 'chunked':
                    chunks = []
                    while True:
                        size = int(self.rfile.readline().split(b';', 1)[0].strip(), 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.read(2)
                    raw_body = b''.join(chunks)
                else:
                    raw_body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                body = json.loads(raw_body)
                calls.append((self.path, body))
                raw = json.dumps({'apiVersion': 'v1', 'kind': 'Status', 'status': 'Success', 'code': 200}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / 'kubeconfig'
                config.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'Config', 'clusters': [{'name': 'fixture', 'cluster': {'server': 'http://127.0.0.1:' + str(server.server_port)}}], 'users': [{'name': 'fixture', 'user': {}}], 'contexts': [{'name': 'fixture', 'context': {'cluster': 'fixture', 'user': 'fixture'}}], 'current-context': 'fixture'}))
                options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Background', 'preconditions': {'uid': 'fixture-uid', 'resourceVersion': '77'}}
                body = root / 'delete.json'
                body.write_text(json.dumps(options))
                route = '/apis/karpenter.sh/v1/nodepools/fixture'
                result = subprocess.run([cli, '--kubeconfig', str(config), 'delete', '--raw=' + route, '-f', str(body)], capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(calls, [(route, options)])
                self.assertEqual(json.loads(result.stdout)['status'], 'Success')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_returned_namespace_or_application_stops_scope(self):
        for returned in ('app', 'namespace'):
            runner = Mock()
            def get(label, kind, name, *args, **kwargs):
                if kind == 'applications.argoproj.io':
                    return {'items': [{}] if returned == 'app' else []}
                return {'metadata': {'name': name}}
            runner.get.side_effect = get
            with self.assertRaises(ValueError):
                m.runtime_absence(runner, record(), True)
            runner.invoke.assert_not_called()

    def test_storage_or_claim_surprise_stops_scope(self):
        for kind in ('pv', 'pvc', 'nodeclaims'):
            runner = Mock(kube=['fixture-kubectl'])
            runner.get.side_effect = lambda label, typ, name, *a, **kw: {'items': []} if typ == 'applications.argoproj.io' else None
            runner.invoke.side_effect = lambda label, command: {'items': [{}] if kind in command else []}
            with self.assertRaises(ValueError):
                m.runtime_absence(runner, record(), True)

    def test_remaining_scope_calls_real_runner_get_signature(self):
        value = record()
        runner = create_autospec(m.Runner, instance=True)
        runner.kube = ['fixture-kubectl']
        def get(label, kind, name, namespace=None, optional=False):
            if kind == 'namespace':
                self.assertTrue(optional)
                return None
            category = 'nodepools' if kind == 'nodepools' else 'nodeclasses' if kind == 'ec2nodeclasses' else None
            return {'items': [object_for(value, category, n) for n in value[category]] if category else []}
        runner.get.side_effect = get
        runner.invoke.return_value = {'items': []}
        m.runtime_absence(runner, value, True)

    def test_unready_controller_stops_before_delete(self):
        runner = Mock()
        runner.get.return_value = {'items': [{'metadata': {'name': name, 'generation': 2}, 'spec': {'replicas': 1}, 'status': {'readyReplicas': 1, 'observedGeneration': 1}} for name in ('karpenter', 'aws-load-balancer-controller')]}
        with self.assertRaises(ValueError):
            m.controller_ready(runner)

    def check_cloud(self, responses, eks=True):
        runner = Mock(kube=['fixture-kubectl'])
        runner.invoke.side_effect = lambda label, command: responses[label]
        current = {'resources': [{'type': 'aws_eks_node_group', 'instances': [{'attributes': {'resources': [{'autoscaling_groups': [{'name': 'fixture-asg'}]}]}}]}]}
        with patch.object(m, 'state', return_value=current), patch.object(h.p, 'kube_auth'):
            return m.cloud_scope(runner, record(), eks)

    def test_four_system_nodes_and_disks_pass(self):
        result = self.check_cloud(cloud_responses(record()))
        self.assertEqual(result['system_instance_count'], 4)
        self.assertEqual(result['captured_volume_total_gib'], 120)
        self.assertFalse(result['volume_inventory_exhaustive'])

    def test_compute_volume_network_dns_and_alb_drift_rejected(self):
        for case in ('compute', 'volume', 'cidr', 'alb', 'targetgroup', 'dns', 'attachment'):
            responses = cloud_responses(record())
            if case == 'compute':
                responses['remaining-compute']['Reservations'][0]['Instances'][0]['InstanceType'] = 'c6i.large'
            elif case == 'volume':
                responses['remaining-captured-disks']['Volumes'].append({'VolumeId': 'disk-12'})
            elif case == 'cidr':
                responses['remaining-eks-network']['cluster']['resourcesVpcConfig']['publicAccessCidrs'] = ['unexpected']
            elif case == 'alb':
                responses['remaining-describe-load-balancers']['LoadBalancers'] = [{'VpcId': 'fixture-vpc'}]
            elif case == 'targetgroup':
                responses['remaining-describe-target-groups']['TargetGroups'] = [{'VpcId': 'fixture-vpc'}]
            elif case == 'dns':
                responses['remaining-dns']['ResourceRecordSets'] = [{'Name': 'demo.test.aureumstack.com.', 'Type': 'A'}]
            else:
                responses['remaining-system-disk-inventory']['Volumes'].append({'VolumeId': 'unexpected-disk'})
            with self.assertRaises(ValueError, msg=case):
                self.check_cloud(responses)

    def test_post_eks_requires_no_compute_or_captured_disks(self):
        self.assertEqual(self.check_cloud(cloud_responses(record(), False), False)['captured_volume_count'], 0)
        responses = cloud_responses(record(), False)
        responses['remaining-captured-disks']['Volumes'] = [{'VolumeId': 'disk-0'}]
        with self.assertRaises(ValueError):
            self.check_cloud(responses, False)

    def test_eks_plan_cannot_delete_other_modules(self):
        gate = {'deleted': ['module.eks.aws_eks_cluster.this', 'module.backup.aws_s3_bucket.this'], 'drift': []}
        with patch.object(m.m, 'plan_gate', return_value=gate):
            with self.assertRaises(ValueError):
                m.plan_gate({}, {}, 'eks')

    def test_backup_inventory_changed_stops_saved_apply(self):
        proof = {'stage': 'final', 'main': 'fixture-main', 'human_reviewed': True, 'inputs_sha256': 'fixture-hash', 'state_sha256': 'fixture-hash', 'runtime_record_sha256': 'fixture-hash', 'created_at_utc': h.p.timestamp(), 'terraform_version': '1.8.0', 'provider_lock_sha256': 'fixture-hash', 'gate': {}, 'backup_inventory_digest': 'old', 'container_inventory_digest': 'same'}
        proof.update({key: 'fixture-hash' for key in ('binary_sha256', 'json_sha256', 'text_sha256')})
        args = SimpleNamespace(proof=Path('/fixture/proof.json'), expected_proof_sha256='fixture-hash', expected_main='fixture-main', inputs=Path('/fixture/inputs.json'), workspace=Path('/fixture/workspace'))
        runner = Mock(state_hash='fixture-hash')
        runner.invoke.side_effect = lambda label, command, **kwargs: {'terraform_version': '1.8.0'} if label == 'terraform-version-before-apply' else b'default' if label == 'terraform-workspace-before-apply' else {}
        with patch.object(h, 'read_private', return_value=proof), patch.object(m, 'require_window'), patch.object(h.p, 'digest', return_value='fixture-hash'), patch.object(h.p, 'private'), patch.object(m, 'state', return_value={'resources': []}), patch.object(m, 'plan_gate', return_value={}), patch.object(m, 'final_inventory', return_value={'backup_inventory_digest': 'changed', 'container_inventory_digest': 'same'}) as inventory, patch.object(h.p, 'write') as write:
            with self.assertRaises(ValueError):
                m.apply_plan(runner, args, {}, 'final')
            write.assert_not_called()
            inventory.assert_called_once()
        self.assertFalse(any('apply' in call.args[1] for call in runner.invoke.call_args_list))

    def test_missing_history_cannot_create_proof(self):
        args = SimpleNamespace(prior_workspace=None, prior_result=None, repair_result=None, observation_directory=None)
        with self.assertRaises(ValueError):
            m.history(args, {})

    def driver(self, root, phase, proof=None):
        workspace = root / 'workspace'
        output = root / ('output-' + phase + '-' + str(len(list(root.glob('output-*')))))
        args = ['entry', phase, '--inputs', str(root / 'inputs.json'), '--workspace', str(workspace), '--output-directory', str(output), '--expected-main', 'fixture-main']
        if proof:
            args += ['--proof', str(proof), '--expected-proof-sha256', 'fixture-hash']
        now = datetime(2026, 9, 13, 13, 0, tzinfo=timezone.utc)
        config = {'implementationBaselineCommit': 'fixture-main', 'inputsSha256': 'fixture-hash', 'recovery': {}, 'runtimeStopUtc': '2026-09-13T14:30:00Z', 'cleanupCompleteByUtc': '2026-09-13T16:00:00Z', 'stateSha256': 'fixture-hash'}
        inputs = {'aws_account_id': 'fixture-owner', 'management_cidr': 'fixture-cidr', 'kubeconfig_path': 'fixture-config', 'recovery_summary_path': 'fixture-summary', 'old_temporary_evidence_lost': True}
        value = record()
        value['managed'] = {}
        runner = Mock(state_hash='fixture-hash', stage='fixture-read', mutation_attempted=False)
        runner.environment = {}
        runner.invoke.return_value = {'Account': 'fixture-owner'}
        approval = m.PHASES[phase]
        env = {approval[0]: approval[1]} if approval else {}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(m.os.environ, env, clear=True))
            stack.enter_context(patch.object(sys, 'argv', args))
            patches = [
                (m, 'source_checks', config), (m.m, 'projection', {'estimated_total_usd': '35.20'}),
                (h.p, 'exact_main', None), (m, 'checked', inputs), (h.p, 'persistent', None),
                (h.p, 'digest', 'fixture-hash'), (m, 'snapshot', None), (m, 'Runner', runner),
                (m, 'history', value), (m, 'state', {}), (m, 'addresses', {}),
                (m, 'runtime_absence', None), (m, 'cloud_scope', {'system_instance_count': 4}),
                (m, 'controller_ready', None), (h, 'now', now),
                (h.p, 'timestamp', '2026-09-13T13:00:00Z'), (m, 'window_digest', 'fixture-window')
            ]
            for owner, key, result in patches:
                stack.enter_context(patch.object(owner, key, return_value=result))
            cleanup = stack.enter_context(patch.object(m, 'configuration_cleanup'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            status = m.main()
        return status, output, cleanup.call_count

    def test_driver_fresh_verification_does_not_authorize_or_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            status, output, calls = self.driver(root, 'verify-remaining')
            self.assertEqual((status, calls), (0, 0))
            proof = json.loads((root / 'workspace/runtime-proof.json').read_text())
            self.assertFalse(proof['human_reviewed'])
            self.assertTrue(proof['schedule_review_required'])
            self.assertFalse((root / 'workspace/remaining-runtime-attempt.json').exists())

    def test_driver_requires_schedule_review_before_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            self.driver(root, 'verify-remaining')
            proof_path = root / 'workspace/runtime-proof.json'
            proof = json.loads(proof_path.read_text())
            proof['human_reviewed'] = True
            reviewed = root / 'workspace/reviewed.json'
            reviewed.write_text(json.dumps(proof))
            reviewed.chmod(0o600)
            status, output, calls = self.driver(root, 'execute-remaining', reviewed)
            self.assertEqual((status, calls), (1, 0))
            self.assertFalse((root / 'workspace/remaining-runtime-attempt.json').exists())

    def test_driver_receipt_and_exclusive_marker_prevent_second_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            self.driver(root, 'verify-remaining')
            proof = json.loads((root / 'workspace/runtime-proof.json').read_text())
            proof.update(human_reviewed=True, schedule_review_required=False)
            reviewed = root / 'workspace/reviewed.json'
            reviewed.write_text(json.dumps(proof))
            reviewed.chmod(0o600)
            status, output, calls = self.driver(root, 'execute-remaining', reviewed)
            self.assertEqual((status, calls), (0, 1))
            receipt = root / 'workspace/runtime-complete.json'
            marker = root / 'workspace/remaining-runtime-attempt.json'
            self.assertTrue(receipt.exists())
            original_marker = marker.read_bytes()
            status, output, calls = self.driver(root, 'execute-remaining', reviewed)
            self.assertEqual((status, calls), (1, 0))
            self.assertEqual(marker.read_bytes(), original_marker)

if __name__ == '__main__':
    unittest.main()
