#!/usr/bin/env python3
"""Offline archive and semantic regression; no cloud or Git mutations."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('archive', Path(__file__).with_name('archive-observability-evidence.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def evidence(status='qualified'):
    checks = [{'id': 'prometheus.target', 'outcome': 'passed', 'observedValue': 'up'},
              {'id': 'identity.rbac-mode', 'outcome': 'passed', 'observedValue': 'operator-credentials-read-only-code; least-privilege-not-verified'}]
    caps = {key: {'status': 'supported-not-verified', 'evidenceCheckIds': []} for key in a.CAPS}
    if status == 'qualified':
        caps['metrics'] = {'status': 'supported-verified', 'evidenceCheckIds': ['prometheus.target']}
    else:
        checks = [{'id': 'runtime.discovery', 'outcome': 'not-run' if status == 'waiting-runtime' else 'failed'}]
    return {'schemaVersion': 'v0.11.8.0', 'qualificationVersion': 'v0.11.8.2', 'environment': 'aws-test',
            'status': status, 'observationWindow': {'startedAt': '2026-09-03T03:15:40Z', 'finishedAt': '2026-09-03T03:16:57Z'},
            'identity': {'awsAccountId': '123456789012', 'awsRegion': 'us-east-1',
                         'clusterName': 'startup-devops-baseline-test',
                         'kubeContext': 'arn:aws:eks:us-east-1:123456789012:cluster/startup-devops-baseline-test',
                         'repositoryCommit': 'a'*40, 'targetRevision': 'a'*40, 'applicationVersion': 'sha-fixture'},
            'approval': {'required': False, 'approved': False, 'reference': None}, 'capabilities': caps, 'checks': checks}


class ArchiveTests(unittest.TestCase):
    def test_matrix_references_and_deferred_prod(self):
        matrix = json.loads((a.ROOT / 'delivery/contracts/v0.11.8.4-multi-environment-closure.json').read_text())
        self.assertEqual(set(matrix['environments']), {'local', 'aws-dev', 'aws-test', 'aws-prod'})
        self.assertFalse(matrix['all_environments_runtime_qualified'])
        self.assertEqual(matrix['environments']['aws-prod']['runtime_evidence'], 'deferred-to-v0.11-tail')
        for value in matrix['environments'].values():
            self.assertTrue((a.ROOT / value['reference']).is_file())
            self.assertFalse(value['new_payload_archived_here'])

    def test_raw_redacted_and_nonqualified(self):
        for status in ('qualified', 'waiting-runtime', 'failed'):
            doc = evidence(status)
            a.validate_evidence(json.dumps(doc), 'raw')
        doc = evidence()
        doc['identity']['awsAccountId'] = '***'
        doc['identity']['kubeContext'] = doc['identity']['kubeContext'].replace('123456789012', '***')
        a.validate_evidence(json.dumps(doc), 'redacted')
        with self.assertRaises(ValueError):
            a.validate_evidence(json.dumps(doc), 'raw')
        self.assertFalse(a.summary(doc)['promotion_eligible'])
        self.assertIsNone(a.summary(doc)['image'])

    def test_negative_semantics(self):
        mutations = [lambda d: d.update(environment='aws-dev'),
                     lambda d: d['identity'].update(targetRevision='b'*40),
                     lambda d: d['checks'][0].update(outcome='failed'),
                     lambda d: d.update(status='waiting-runtime'),
                     lambda d: d['checks'].append(copy.deepcopy(d['checks'][0])),
                     lambda d: d['capabilities']['metrics'].update(evidenceCheckIds=['unknown']),
                     lambda d: d['observationWindow'].update(finishedAt='2020-01-01T00:00:00Z')]
        for mutation in mutations:
            doc = evidence()
            mutation(doc)
            with self.assertRaises(ValueError):
                a.validate_evidence(json.dumps(doc), 'raw')
        with self.assertRaises(ValueError):
            a.read_json('{"status":1,"status":2}')

    def test_prod_needs_approval(self):
        doc = evidence()
        doc['environment'] = 'aws-prod'
        doc['identity']['clusterName'] = 'startup-devops-baseline-prod'
        doc['identity']['kubeContext'] = doc['identity']['kubeContext'].replace('-test', '-prod')
        with self.assertRaises(ValueError):
            a.validate_evidence(json.dumps(doc), 'raw')
        doc['approval'] = {'required': True, 'approved': True, 'reference': 'REVIEW-1'}
        a.validate_evidence(json.dumps(doc), 'raw')

    def test_archive_duplicate_append_and_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'archive'
            source = Path(directory) / 'source.json'
            raw = json.dumps(evidence()).encode()
            source.write_bytes(raw)
            first = a.register(root, source, 'raw', 'REVIEW-1')
            self.assertEqual((root / first / 'evidence.json').read_bytes(), raw)
            baseline = Path(directory) / 'baseline.json'
            baseline.write_text(json.dumps(a.verify(root)))
            with self.assertRaises(FileExistsError):
                a.register(root, source, 'raw', 'REVIEW-2')
            source.write_text(json.dumps(evidence('failed')))
            a.register(root, source, 'raw', 'REVIEW-3')
            self.assertEqual(len(a.verify(root, baseline)['entries']), 2)
            (root / first).rename(Path(directory) / 'removed-entry')
            with self.assertRaisesRegex(ValueError, 'Append-only'):
                a.verify(root, baseline)

    def test_tamper_and_incomplete_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'archive'
            source = Path(directory) / 'source.json'
            source.write_text(json.dumps(evidence()))
            first = a.register(root, source, 'raw', 'REVIEW-1')
            (root / first / 'evidence.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                a.verify(root)
            (root / first / 'evidence.json').unlink()
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                a.verify(root)

    def test_repo_archive_refused(self):
        with self.assertRaises(ValueError):
            a.safe_root(a.ROOT / 'private-evidence')


if __name__ == '__main__':
    unittest.main(verbosity=2)
