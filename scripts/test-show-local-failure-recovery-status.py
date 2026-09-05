#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'show_failure_recovery_status', ROOT / 'scripts/show-local-failure-recovery-status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Tests(unittest.TestCase):
    def test_reports_manual_abort_checkpoint_without_token_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle'
            bundle.mkdir()
            for phase in M.PHASES[:4]:
                (bundle / f'{phase}.passed.json').write_text('{}')
            (bundle / 'fault-token.private').write_text('must-not-appear')
            result = M.inspect(bundle)
            self.assertEqual(result['next_phase'], 'abort-check')
            self.assertIn('manual abort', result['manual_action'])
            self.assertNotIn('must-not-appear', json.dumps(result))

    def test_reports_latest_failure_and_log_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle'
            attempt = bundle / 'prepare-attempt'
            attempt.mkdir(parents=True)
            (attempt / 'failure.json').write_text(json.dumps({'error': 'baseline not healthy'}))
            result = M.inspect(bundle)
            self.assertEqual(result['next_phase'], 'prepare')
            self.assertEqual(result['unresolved_failures']['prepare'], 'baseline not healthy')
            self.assertEqual(result['latest_attempts']['prepare'], str(attempt))


if __name__ == '__main__':
    unittest.main()
