#!/usr/bin/env python3
"""Show redaction-safe local failure/recovery bundle progress and next action."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PHASES = ('prepare', 'arm', 'traffic', 'rejection-review', 'abort-check',
          'recovery-approval', 'restore', 'final')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inspect(bundle):
    bundle = Path(bundle).expanduser().resolve()
    require(not bundle.is_relative_to(ROOT), 'Private bundle must be outside repository')
    require(bundle.is_dir(), 'Bundle directory does not exist')
    passed = []
    attempts = {}
    failures = {}
    for phase in PHASES:
        marker = bundle / f'{phase}.passed.json'
        if marker.is_file():
            passed.append(phase)
        phase_attempts = sorted((path for path in bundle.glob(f'{phase}-*') if path.is_dir()),
                                key=lambda path: path.stat().st_mtime)
        if phase_attempts:
            latest = phase_attempts[-1]
            attempts[phase] = str(latest)
            failure = latest / 'failure.json'
            if failure.is_file() and not marker.is_file():
                failures[phase] = json.loads(failure.read_text()).get('error', 'unknown failure')
    expected = list(PHASES[:len(passed)])
    require(passed == expected, 'Passed markers are not a contiguous phase prefix')
    next_phase = PHASES[len(passed)] if len(passed) < len(PHASES) else None
    manual_action = None
    if next_phase == 'abort-check':
        manual_action = 'Inspect abort state; run the reviewed manual abort once only if abort is not already true.'
    elif next_phase == 'final':
        manual_action = ('Verify desired baseline and disabled fault; run the reviewed manual retry once only '
                         'if the Rollout remains aborted, then wait for Healthy convergence.')
    result = {'bundle': str(bundle), 'passed_phases': passed, 'next_phase': next_phase,
              'manual_action': manual_action, 'latest_attempts': attempts,
              'unresolved_failures': failures,
              'runtime_qualified': (bundle / 'qualification.json').is_file()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.bundle), indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Stopped: {exc}\nNo runtime operation was performed.\n')


if __name__ == '__main__':
    main()
