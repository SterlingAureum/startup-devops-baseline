#!/usr/bin/env python3
"""Run the real historical checker on isolated positive/negative source trees."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = Path('clusters/aws/overlays/test-feature-qualification/root-app.yaml')
CONTRACT = Path('delivery/contracts/v0.11.8.2.0-aws-test-qualification-prerequisites.json')


class PreviewRegistration(unittest.TestCase):
    def test_checker_positive_and_negative_trees(self):
        with tempfile.TemporaryDirectory(prefix='preview-regression-') as directory:
            root = Path(directory)
            for name in ('clusters', 'scripts'):
                shutil.copytree(ROOT / name, root / name)
            (root / CONTRACT).parent.mkdir(parents=True)
            shutil.copy2(ROOT / CONTRACT, root / CONTRACT)
            original = (root / PREVIEW).read_text()
            contract = (root / CONTRACT).read_text()

            def run():
                return subprocess.run(['bash', str(root / 'scripts/validate-active-gitops-revisions.sh')],
                                      text=True, capture_output=True, timeout=30)

            result = run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            mutations = {
                'wrong revision': lambda x: x['spec']['source'].update(targetRevision='main'),
                'wrong source path': lambda x: x['spec']['source'].update(path='clusters/aws/overlays/dev'),
                'wrong repository': lambda x: x['spec']['source'].update(repoURL='https://example.invalid/wrong.git'),
                'wrong name': lambda x: x['metadata'].update(name='unapproved-root'),
                'wrong destination': lambda x: x['spec']['destination'].update(namespace='startup-apps'),
                'automatic sync': lambda x: x['spec'].update(syncPolicy={'automated': {'prune': True}}),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    value = yaml.safe_load(original)
                    mutate(value)
                    (root / PREVIEW).write_text(yaml.safe_dump(value))
                    self.assertNotEqual(run().returncode, 0)
            (root / PREVIEW).write_text(original)

            # No wildcard exemption for other Applications in the same folder.
            unexpected = root / PREVIEW.parent / 'unapproved.yaml'
            unexpected.write_text(original)
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unclassified', result.stderr + result.stdout)
            unexpected.unlink()

            for env in ('test', 'prod'):
                target = root / f'clusters/aws/overlays/{env}/root-app.yaml'
                previous = target.read_text()
                value = yaml.safe_load(previous)
                value['spec']['source']['targetRevision'] = 'feature/unapproved'
                target.write_text(yaml.safe_dump(value))
                self.assertNotEqual(run().returncode, 0)
                target.write_text(previous)

            probe = root / 'scripts/unapproved-preview.txt'
            probe.write_text('targetRevision: ' + 'feature/unapproved\n')
            self.assertNotEqual(run().returncode, 0)
            probe.unlink()

            changed = json.loads(contract)
            changed['qualification_revision'] = 'feature/unapproved'
            (root / CONTRACT).write_text(json.dumps(changed))
            self.assertNotEqual(run().returncode, 0)
            (root / CONTRACT).write_text(contract)

            (root / PREVIEW).unlink()
            self.assertNotEqual(run().returncode, 0)
            # Historical state without either the contract or preview still works.
            (root / CONTRACT).unlink()
            result = run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (root / PREVIEW).write_text(original)
            self.assertNotEqual(run().returncode, 0)
            print('2 positive trees and 13 negative preview/revision cases passed.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
