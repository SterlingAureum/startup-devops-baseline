"""Fixed-fake Application freeze/orphan/delete adapter.

All identity, clock, observation and result bytes are scripted fixtures.  This
module has no Kubernetes, cloud, Terraform, subprocess or environment access.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from guarded_attempt_journal import AttemptJournal
from guarded_cleanup_rules import validate_cleanup_step
from guarded_runtime_rules import (RuleViolation, json_object, parse_utc, require,
                                   state_addresses, validate_confirmations,
                                   validate_observation_age, validate_proof,
                                   validate_window)
from guarded_runtime_simulation_v6774 import ScenarioClock, _budget


VERSION = 'v0.11.9.3.6.7.7.7'
PHASE = 'freeze-applications'
ENVIRONMENTS = ('aws-dev', 'aws-test', 'aws-prod')
ARTIFACT_KEYS = {'inputs', 'scope', 'state'}
KNOWN_FINALIZERS = {
    'resources-finalizer.argocd.argoproj.io',
    'resources-finalizer.argocd.argoproj.io/background',
}
APPLICATION_KEYS = {
    'name', 'namespace', 'uid', 'resource_version', 'source_sha256',
    'destination_sha256', 'automated_sync_enabled', 'finalizers',
    'deletion_requested', 'active_operation',
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class FreezeSimulationStopped(RuleViolation):
    def __init__(self, stage: str, attempted: bool):
        super().__init__('offline-freeze-simulation-stopped')
        self.report = {
            'status': 'offline-freeze-simulation-stopped',
            'stage': stage,
            'simulation_only': True,
            'simulated_call_attempted': attempted,
            'kubernetes_mutation_executed': False,
            'aws_mutation_executed': False,
            'terraform_command_executed': False,
            'automatic_retry_performed': False,
            'preserve_private_evidence': True,
        }


class FreezeScenarioTransport:
    """Exact scripted observations and acknowledgements; never a live backend."""
    def __init__(self, observations: dict[str, bytes], results: dict[str, bytes], *,
                 fail_at: str = ''):
        require(isinstance(observations, dict) and isinstance(results, dict),
                'freeze-scenario-schema')
        self.observations = dict(observations)
        self.results = dict(results)
        self.fail_at = fail_at
        self.calls = []

    def observe(self, label: str) -> bytes:
        require(isinstance(label, str) and re.fullmatch(
            r'(?:pre|immediate|frozen|post|app-[0-9]{4}-(?:freeze-pre|freeze-post|orphan-pre|orphan-post|delete-post))',
            label), 'freeze-observation-label')
        self.calls.append(('observe', label))
        require(self.fail_at != label and label in self.observations,
                'freeze-simulated-observation-failure')
        return self.observations[label]

    def mutate(self, operation: str, identity_sha256: str) -> bytes:
        require(isinstance(operation, str) and re.fullmatch(
            r'(?:freeze|orphan|delete)-app-[0-9]{4}', operation),
            'freeze-operation-tag')
        require(isinstance(identity_sha256, str)
                and re.fullmatch('[0-9a-f]{64}', identity_sha256),
                'freeze-identity-digest')
        self.calls.append(('fake-mutate', operation, identity_sha256))
        require(self.fail_at != operation and operation in self.results,
                'freeze-simulated-call-uncertain')
        return self.results[operation]


def _application(value: dict, *, initial: bool | None = None) -> dict:
    require(isinstance(value, dict) and set(value) == APPLICATION_KEYS,
            'freeze-application-schema')
    require(isinstance(value['name'], str)
            and re.fullmatch(r'[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?', value['name'])
            and value['namespace'] == 'argocd'
            and isinstance(value['uid'], str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value['uid'])
            and isinstance(value['resource_version'], str)
            and re.fullmatch(r'[1-9][0-9]*', value['resource_version'])
            and isinstance(value['source_sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', value['source_sha256'])
            and isinstance(value['destination_sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', value['destination_sha256'])
            and type(value['automated_sync_enabled']) is bool
            and type(value['deletion_requested']) is bool
            and type(value['active_operation']) is bool,
            'freeze-application-identity')
    require(isinstance(value['finalizers'], list)
            and len(value['finalizers']) == len(set(value['finalizers']))
            and set(value['finalizers']) <= KNOWN_FINALIZERS,
            'freeze-application-finalizer')
    if initial is True:
        require(value['automated_sync_enabled'] is True
                and value['deletion_requested'] is False
                and value['active_operation'] is False
                and len(value['finalizers']) == 1,
                'freeze-application-initial-state')
    return value


def _stable_identity(before: dict, after: dict) -> None:
    keys = ('name', 'namespace', 'uid', 'source_sha256', 'destination_sha256')
    require(all(before[key] == after[key] for key in keys),
            'freeze-application-stable-identity')
    require(before['resource_version'] != after['resource_version'],
            'freeze-resource-version-not-advanced')
    require(after['deletion_requested'] is False
            and after['active_operation'] is False,
            'freeze-application-active-or-deleting')


def _result(raw: bytes) -> bool:
    result = json_object(raw)
    require(type(result.get('success')) is bool, 'freeze-unknown-call-result')
    return result['success']


def simulation_receipt(report: dict) -> dict:
    """Convert only a confirmed offline stage report to a synthetic receipt."""
    require(isinstance(report, dict), 'simulation-report-schema')
    phase = report.get('phase')
    expected = {
        'freeze-applications': ('offline-freeze-stage-simulation-complete', VERSION),
        'drain-external-secrets': ('offline-cleanup-stage-simulation-complete', 'v0.11.9.3.6.7.7.5'),
        'delete-business-namespaces': ('offline-cleanup-stage-simulation-complete', 'v0.11.9.3.6.7.7.5'),
        'drain-runtime': ('offline-cleanup-stage-simulation-complete', 'v0.11.9.3.6.7.7.5'),
        'delete-node-config': ('offline-cleanup-stage-simulation-complete', 'v0.11.9.3.6.7.7.5'),
        'eks-delete': ('offline-destroy-stage-simulation-complete', 'v0.11.9.3.6.7.7.4'),
        'eni-sg-cleanup': ('offline-cleanup-stage-simulation-complete', 'v0.11.9.3.6.7.7.5'),
        'final-delete': ('offline-destroy-stage-simulation-complete', 'v0.11.9.3.6.7.7.4'),
    }
    require(phase in expected and report.get('status') == expected[phase][0]
            and report.get('version') == expected[phase][1]
            and report.get('environment') in ENVIRONMENTS
            and report.get('simulation_only') is True
            and report.get('live_execution_authorized') is False
            and report.get('prod_qualified') is False
            and report.get('terraform_command_executed') is False
            and report.get('automatic_retry_performed') is False,
            'simulation-report-not-confirmed')
    if phase in ('eks-delete', 'final-delete'):
        require(report.get('cloud_mutation_executed') is False,
                'simulation-report-live-effect')
    else:
        require(report.get('kubernetes_mutation_executed') is False
                and report.get('aws_mutation_executed') is False,
                'simulation-report-live-effect')
    raw = canonical({'step': phase, 'environment': report['environment'],
                     'confirmed': True, 'simulation_only': True})
    return {'step': phase, 'raw': raw.decode(), 'sha256': sha(raw)}


class OfflineFreezeAdapter:
    """First-stage fixed-fake adapter for explicit dev/test/prod profiles."""
    def __init__(self, environment: str, main: str, *, repository_root: Path):
        require(environment in ENVIRONMENTS, 'freeze-explicit-environment')
        require(isinstance(main, str) and re.fullmatch('[0-9a-f]{40}', main),
                'freeze-simulation-main')
        self.environment = environment
        self.main = main
        self.repository_root = Path(repository_root)

    @staticmethod
    def _clocks(approval: dict, current: str) -> None:
        validate_window(approval['start_utc'], approval['end_utc'], current,
                        maximum_seconds=28800, minimum_remaining_seconds=60)
        validate_proof(approval['created_at'], approval['expires_at'], current,
                       approval['end_utc'], ttl_seconds=900,
                       original_created=approval['original_created_at'])

    @staticmethod
    def _deadline(approval: dict, current: str) -> None:
        require(parse_utc(current) <= parse_utc(approval['end_utc']),
                'freeze-simulation-window-expired')

    def _inputs(self, artifacts: dict[str, bytes], approval_raw: bytes,
                expected_approval_sha256: str, journal_directory: Path,
                confirmations: dict, current: str):
        require(isinstance(artifacts, dict) and set(artifacts) == ARTIFACT_KEYS
                and all(isinstance(value, bytes) for value in artifacts.values()),
                'freeze-simulation-artifacts')
        require(isinstance(approval_raw, bytes)
                and sha(approval_raw) == expected_approval_sha256,
                'freeze-simulation-approval-drift')
        approval = json_object(approval_raw)
        require(approval.get('schema') == 'offline-freeze-approval-v1'
                and approval.get('simulation_only') is True
                and approval.get('environment') == self.environment
                and approval.get('phase') == PHASE
                and approval.get('main') == self.main
                and approval.get('hashes') == {key: sha(value)
                                                for key, value in artifacts.items()},
                'freeze-simulation-approval-scope')
        require(isinstance(approval.get('journal_directory'), str)
                and Path(journal_directory).is_absolute()
                and str(journal_directory) == approval['journal_directory'],
                'freeze-simulation-journal-path')
        required = {'CONFIRM_' + self.environment.upper().replace('-', '_') +
                    '_OFFLINE_FREEZE':
                    'simulate-reviewed-' + self.environment + '-freeze-applications-once'}
        validate_confirmations(confirmations, self.environment, required)
        self._clocks(approval, current)
        inputs, scope, state = (json_object(artifacts[key])
                                for key in ('inputs', 'scope', 'state'))
        require(inputs.get('environment') == self.environment
                and inputs.get('region') == 'us-east-1'
                and isinstance(inputs.get('account'), str)
                and re.fullmatch('[0-9]{12}', inputs['account'])
                and isinstance(inputs.get('cluster'), str)
                and inputs['cluster'].endswith('-' + self.environment.removeprefix('aws-'))
                and _budget(inputs.get('budget_limit_usd')) ==
                    _budget(approval.get('budget_limit_usd')),
                'freeze-simulation-input-scope')
        state_addresses(state)
        root = 'startup-devops-' + self.environment + '-root'
        applications = scope.get('applications')
        require(scope.get('environment') == self.environment
                and scope.get('phase') == PHASE
                and scope.get('root_name') == root
                and isinstance(applications, list) and len(applications) >= 2,
                'freeze-simulation-review-scope')
        applications = [_application(row, initial=True) for row in applications]
        require(applications[0]['name'] == root
                and [row['name'] for row in applications[1:]] ==
                    sorted(row['name'] for row in applications[1:])
                and len({row['name'] for row in applications}) == len(applications),
                'freeze-application-order-or-duplicate')
        return approval, inputs, scope, state, applications

    def _observe(self, raw: bytes, inputs: dict, approval: dict,
                 state_raw: bytes, current: str, *, cleanup_gate=False) -> dict:
        value = json_object(raw)
        require(value.get('identity') == {key: inputs[key] for key in
                ('environment', 'region', 'account', 'cluster')}
                and value.get('main') == self.main
                and value.get('state_sha256') == sha(state_raw)
                and value.get('inventory_complete') is True,
                'freeze-simulation-observation-scope')
        validate_observation_age(value.get('observed_at'), current, ttl_seconds=60)
        require(_budget(value.get('estimated_total_usd')) <=
                _budget(approval['budget_limit_usd']), 'freeze-simulation-budget')
        if cleanup_gate:
            validate_cleanup_step((), PHASE, value.get('cleanup'))
        rows = value.get('applications')
        require(isinstance(rows, list), 'freeze-observed-application-set')
        value['applications'] = [_application(row) for row in rows]
        require(len({row['name'] for row in value['applications']}) == len(rows),
                'freeze-observed-application-duplicate')
        return value

    def _journal(self, directory: Path, artifacts: dict[str, bytes],
                 approval_raw: bytes, timestamp: str) -> AttemptJournal:
        binding = {'environment': self.environment, 'phase': PHASE,
                   'main': self.main, 'inputs_sha256': sha(artifacts['inputs']),
                   'state_sha256': sha(artifacts['state']),
                   'proof_sha256': sha(approval_raw),
                   'scope_sha256': sha(artifacts['scope'])}
        return AttemptJournal.reserve(directory, binding, timestamp,
                                      repository_root=self.repository_root)

    def _invoke(self, handle: AttemptJournal, operation: str, identity: dict,
                observed_at: str, approval: dict, transport: FreezeScenarioTransport,
                clock: ScenarioClock, attempted: list[bool]) -> None:
        now = clock.current(); self._clocks(approval, now)
        handle.before(operation, now)
        now = clock.current(); self._clocks(approval, now)
        validate_observation_age(observed_at, now, ttl_seconds=60)
        attempted[0] = True
        if not _result(transport.mutate(operation, sha(canonical(identity)))):
            handle.failure(operation, clock.current())
            raise RuleViolation('freeze-simulated-explicit-call-failure')

    def run(self, artifacts: dict[str, bytes], approval_raw: bytes,
            expected_approval_sha256: str, *, journal_directory: Path,
            confirmations: dict, transport: FreezeScenarioTransport,
            clock: ScenarioClock) -> dict:
        require(type(transport) is FreezeScenarioTransport
                and type(clock) is ScenarioClock, 'fixed-freeze-fake-only')
        stage, attempted, handle = 'local-inputs', [False], None
        try:
            artifacts = dict(artifacts)
            approval, inputs, scope, state, captured = self._inputs(
                artifacts, approval_raw, expected_approval_sha256,
                journal_directory, confirmations, clock.current())
            stage = 'pre-observation'
            pre = self._observe(transport.observe('pre'), inputs, approval,
                                artifacts['state'], clock.current(), cleanup_gate=True)
            require(pre['applications'] == captured, 'freeze-pre-scope-drift')
            stage = 'immediate-observation'
            immediate = self._observe(transport.observe('immediate'), inputs, approval,
                                      artifacts['state'], clock.current(), cleanup_gate=True)
            require(immediate['applications'] == captured,
                    'freeze-immediate-scope-drift')
            self._inputs(artifacts, approval_raw, expected_approval_sha256,
                         journal_directory, confirmations, clock.current())
            handle = self._journal(journal_directory, artifacts, approval_raw,
                                   clock.current())
            current = [dict(row) for row in captured]
            operations = []
            for index in range(len(captured)):
                label = str(index).zfill(4)
                stage = 'freeze-app-' + label
                before = self._observe(transport.observe('app-' + label + '-freeze-pre'),
                    inputs, approval, artifacts['state'], clock.current(), cleanup_gate=True)
                require(before['applications'] == current,
                        'freeze-application-precondition')
                operation = 'freeze-app-' + label
                self._invoke(handle, operation, current[index], before['observed_at'],
                             approval, transport, clock, attempted)
                after = self._observe(transport.observe('app-' + label + '-freeze-post'),
                    inputs, approval, artifacts['state'], clock.current())
                require(len(after['applications']) == len(current),
                        'freeze-application-post-set')
                for position, row in enumerate(after['applications']):
                    if position == index:
                        _stable_identity(current[position], row)
                        require(row['automated_sync_enabled'] is False
                                and row['finalizers'] == current[position]['finalizers'],
                                'freeze-application-postcondition')
                    else:
                        require(row == current[position],
                                'freeze-unrelated-application-drift')
                current = after['applications']
                self._deadline(approval, clock.current())
                handle.success(operation, clock.current()); operations.append(operation)
            frozen = self._observe(transport.observe('frozen'), inputs, approval,
                                   artifacts['state'], clock.current())
            require(frozen['applications'] == current
                    and all(not row['automated_sync_enabled']
                            and not row['active_operation']
                            and not row['deletion_requested'] for row in current),
                    'freeze-all-applications-postcondition')
            for index in range(len(captured)):
                label = str(index).zfill(4)
                stage = 'orphan-app-' + label
                before = self._observe(transport.observe('app-' + label + '-orphan-pre'),
                    inputs, approval, artifacts['state'], clock.current())
                require(before['applications'] == current and current,
                        'orphan-application-precondition')
                target = current[0]
                require(target['name'] == captured[index]['name']
                        and target['finalizers'] == captured[index]['finalizers']
                        and target['automated_sync_enabled'] is False,
                        'orphan-application-order')
                operation = 'orphan-app-' + label
                self._invoke(handle, operation, target, before['observed_at'],
                             approval, transport, clock, attempted)
                orphaned = self._observe(transport.observe('app-' + label + '-orphan-post'),
                    inputs, approval, artifacts['state'], clock.current())
                require(len(orphaned['applications']) == len(current),
                        'orphan-application-post-set')
                _stable_identity(target, orphaned['applications'][0])
                require(orphaned['applications'][0]['finalizers'] == []
                        and orphaned['applications'][0]['automated_sync_enabled'] is False
                        and orphaned['applications'][1:] == current[1:],
                        'orphan-application-postcondition')
                self._deadline(approval, clock.current())
                handle.success(operation, clock.current()); operations.append(operation)
                current = orphaned['applications']
                stage = 'delete-app-' + label
                operation = 'delete-app-' + label
                self._invoke(handle, operation, current[0], orphaned['observed_at'],
                             approval, transport, clock, attempted)
                deleted = self._observe(transport.observe('app-' + label + '-delete-post'),
                    inputs, approval, artifacts['state'], clock.current())
                require(deleted['applications'] == current[1:],
                        'delete-application-postcondition')
                self._deadline(approval, clock.current())
                handle.success(operation, clock.current()); operations.append(operation)
                current = deleted['applications']
            final = self._observe(transport.observe('post'), inputs, approval,
                                  artifacts['state'], clock.current())
            require(final['applications'] == []
                    and final.get('active_application_operations') == 0
                    and final.get('state_unchanged') is True,
                    'freeze-final-postcondition')
            self._deadline(approval, clock.current())
            handle.complete(tuple(operations), clock.current())
            snapshot = handle.snapshot()
            report = {
                'status': 'offline-freeze-stage-simulation-complete',
                'version': VERSION,
                'environment': self.environment,
                'phase': PHASE,
                'simulation_only': True,
                'application_count': len(captured),
                'simulated_mutation_count': len(operations),
                'journal_marker_sha256': handle.marker_sha256,
                'journal_events_sha256': snapshot['events_sha256'],
                'kubernetes_mutation_executed': False,
                'aws_mutation_executed': False,
                'terraform_command_executed': False,
                'automatic_retry_performed': False,
                'live_execution_authorized': False,
                'prod_qualified': False,
            }
            report['confirmed_receipt'] = simulation_receipt(report)
            return report
        except FreezeSimulationStopped:
            raise
        except Exception:
            raise FreezeSimulationStopped(stage, attempted[0]) from None
        finally:
            if handle is not None:
                handle.close()
