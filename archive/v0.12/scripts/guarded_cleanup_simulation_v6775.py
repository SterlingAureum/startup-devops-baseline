"""Fixed-fake ESO/runtime and captured ENI/SG adapter composition.

This module has no SDK, CLI, subprocess, environment or system-clock access.
All observations are scripted bytes. Simulation approval is never live authority.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from guarded_attempt_journal import AttemptJournal
from guarded_cleanup_rules import (CLEANUP_STEPS, eni_decision, sg_decision,
                                   validate_cleanup_step)
from guarded_runtime_rules import (RuleViolation, json_object, require, state_addresses,
                                   parse_utc,
                                   validate_confirmations, validate_observation_age,
                                   validate_proof, validate_window)
from guarded_runtime_simulation_v6774 import ScenarioClock, _budget

VERSION = 'v0.11.9.3.6.7.7.5'
PHASES = ('drain-external-secrets', 'delete-business-namespaces',
          'drain-runtime', 'delete-node-config', 'eni-sg-cleanup')
ARTIFACT_KEYS = {'inputs', 'scope', 'state'}
BUSINESS_NAMESPACES = {'startup-apps', 'data-platform', 'observability'}
RUNTIME_KEYS = ('nodeclaims', 'persistent_volumes', 'captured_runtime_compute',
                'captured_pv_volumes', 'load_balancers', 'target_groups',
                'test_dns_records')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class CleanupSimulationStopped(RuleViolation):
    def __init__(self, stage: str, attempted: bool):
        super().__init__('offline-cleanup-simulation-stopped')
        self.report = {
            'status': 'offline-cleanup-simulation-stopped', 'stage': stage,
            'simulation_only': True, 'simulated_call_attempted': attempted,
            'kubernetes_mutation_executed': False, 'aws_mutation_executed': False,
            'terraform_command_executed': False, 'automatic_retry_performed': False,
            'preserve_private_evidence': True,
        }


class CleanupScenarioTransport:
    """Scripted observations and mutation acknowledgements, with no backend."""
    def __init__(self, observations: dict[str, bytes], results: dict[str, bytes], *,
                 fail_at: str = ''):
        require(isinstance(observations, dict) and isinstance(results, dict),
                'cleanup-scenario-schema')
        self.observations = dict(observations)
        self.results = dict(results)
        self.fail_at = fail_at
        self.calls = []

    def observe(self, label: str) -> bytes:
        require(isinstance(label, str) and re.fullmatch(
            r'(?:pre|immediate|post|eni-post|sg-post|object-[0-9]{4}-(?:pre|post))', label),
            'cleanup-observation-label')
        self.calls.append(('observe', label))
        require(self.fail_at != label and label in self.observations,
                'cleanup-simulated-observation-failure')
        return self.observations[label]

    def mutate(self, operation: str, identity_sha256: str) -> bytes:
        require(isinstance(operation, str) and re.fullmatch(
            r'(?:delete-object-[0-9]{4}|delete-captured-eni|delete-captured-sg)', operation),
            'cleanup-operation-tag')
        require(isinstance(identity_sha256, str)
                and re.fullmatch('[0-9a-f]{64}', identity_sha256),
                'cleanup-identity-digest')
        self.calls.append(('fake-mutate', operation, identity_sha256))
        require(self.fail_at != operation and operation in self.results,
                'cleanup-simulated-call-uncertain')
        return self.results[operation]


def _receipt_prefix(scope: dict, environment: str, phase: str) -> tuple[str, ...]:
    rows = scope.get('receipts')
    require(isinstance(rows, list), 'cleanup-simulation-receipts')
    completed = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'step', 'raw', 'sha256'}
                and isinstance(row['raw'], str)
                and sha(row['raw'].encode()) == row['sha256'],
                'cleanup-simulation-receipt-drift')
        receipt = json_object(row['raw'].encode())
        require(receipt.get('environment') == environment
                and receipt.get('step') == row['step']
                and receipt.get('confirmed') is True
                and receipt.get('simulation_only') is True,
                'cleanup-simulation-unconfirmed-receipt')
        completed.append(row['step'])
    index = CLEANUP_STEPS.index(phase)
    require(tuple(completed) == CLEANUP_STEPS[:index],
            'cleanup-simulation-receipt-prefix')
    return tuple(completed)


def _object(value: dict) -> dict:
    keys = {'api_version', 'kind', 'name', 'namespace', 'uid', 'resource_version',
            'finalizers', 'deletion_requested'}
    require(isinstance(value, dict) and set(value) == keys,
            'cleanup-object-schema')
    require(value['kind'] in ('Namespace', 'NodePool', 'EC2NodeClass'),
            'cleanup-object-kind')
    versions = {'Namespace': 'v1', 'NodePool': 'karpenter.sh/v1',
                'EC2NodeClass': 'karpenter.k8s.aws/v1'}
    require(value['api_version'] == versions[value['kind']]
            and isinstance(value['name'], str)
            and re.fullmatch(r'[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?', value['name'])
            and value['namespace'] == ''
            and isinstance(value['uid'], str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value['uid'])
            and isinstance(value['resource_version'], str)
            and re.fullmatch(r'[1-9][0-9]*', value['resource_version'])
            and type(value['deletion_requested']) is bool,
            'cleanup-object-identity')
    require(isinstance(value['finalizers'], list)
            and all(isinstance(x, str) for x in value['finalizers'])
            and len(value['finalizers']) == len(set(value['finalizers'])),
            'cleanup-object-finalizers')
    allowed = {'Namespace': {'kubernetes'}, 'NodePool': {'karpenter.sh/termination'},
               'EC2NodeClass': {'karpenter.sh/termination'}}[value['kind']]
    require(set(value['finalizers']) <= allowed, 'cleanup-unknown-finalizer')
    return value


def _external_secret(value: dict) -> dict:
    keys = {'api_version', 'kind', 'name', 'namespace', 'uid', 'resource_version',
            'finalizers', 'deletion_requested', 'creation_policy', 'deletion_policy'}
    require(isinstance(value, dict) and set(value) == keys
            and value['api_version'] == 'external-secrets.io/v1'
            and value['kind'] == 'ExternalSecret'
            and isinstance(value['name'], str) and bool(value['name'])
            and isinstance(value['namespace'], str) and value['namespace'] in BUSINESS_NAMESPACES
            and isinstance(value['uid'], str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value['uid'])
            and isinstance(value['resource_version'], str)
            and re.fullmatch(r'[1-9][0-9]*', value['resource_version'])
            and type(value['deletion_requested']) is bool
            and value['creation_policy'] in ('Owner', 'Orphan', 'Merge', 'CreateOrMerge')
            and value['deletion_policy'] in ('Retain', 'Delete', 'Merge'),
            'cleanup-external-secret-schema')
    require(isinstance(value['finalizers'], list)
            and len(value['finalizers']) == len(set(value['finalizers']))
            and set(value['finalizers']) <= {
                'externalsecrets.external-secrets.io/externalsecret-cleanup'},
            'cleanup-external-secret-finalizer')
    return value


def _network_scope(value: dict) -> dict:
    require(isinstance(value, dict), 'cleanup-network-scope')
    result = dict(value)
    for key in ('subnet_ids', 'instance_ids'):
        require(isinstance(result.get(key), list), 'cleanup-network-scope')
        result[key] = tuple(result[key])
    return result


class OfflineCleanupAdapter:
    """Five dependency stages across explicit dev/test/prod fake profiles."""
    def __init__(self, environment: str, phase: str, main: str, *,
                 repository_root: Path):
        require(environment in ('aws-dev', 'aws-test', 'aws-prod'),
                'cleanup-explicit-environment')
        require(phase in PHASES, 'cleanup-simulation-phase')
        require(isinstance(main, str) and re.fullmatch('[0-9a-f]{40}', main),
                'cleanup-simulation-main')
        self.environment, self.phase, self.main = environment, phase, main
        self.repository_root = Path(repository_root)

    def _clocks(self, approval: dict, current: str) -> None:
        validate_window(approval['start_utc'], approval['end_utc'], current,
                        maximum_seconds=28800, minimum_remaining_seconds=60)
        validate_proof(approval['created_at'], approval['expires_at'], current,
                       approval['end_utc'], ttl_seconds=900,
                       original_created=approval['original_created_at'])

    @staticmethod
    def _deadline(approval: dict, current: str) -> None:
        require(parse_utc(current) <= parse_utc(approval['end_utc']),
                'cleanup-simulation-window-expired')

    def _deadline_now(self, approval: dict, clock: ScenarioClock) -> str:
        current = clock.current()
        self._deadline(approval, current)
        return current

    def _inputs(self, artifacts: dict[str, bytes], approval_raw: bytes,
                expected_approval_sha256: str, journal_directory: Path,
                confirmations: dict, current: str):
        require(isinstance(artifacts, dict) and set(artifacts) == ARTIFACT_KEYS
                and all(isinstance(v, bytes) for v in artifacts.values()),
                'cleanup-simulation-artifacts')
        require(isinstance(approval_raw, bytes)
                and sha(approval_raw) == expected_approval_sha256,
                'cleanup-simulation-approval-drift')
        approval = json_object(approval_raw)
        require(approval.get('schema') == 'offline-cleanup-approval-v1'
                and approval.get('simulation_only') is True
                and approval.get('environment') == self.environment
                and approval.get('phase') == self.phase
                and approval.get('main') == self.main
                and approval.get('hashes') == {k: sha(v) for k, v in artifacts.items()},
                'cleanup-simulation-approval-scope')
        require(isinstance(approval.get('journal_directory'), str)
                and Path(journal_directory).is_absolute()
                and str(journal_directory) == approval['journal_directory'],
                'cleanup-simulation-journal-path')
        required = {'CONFIRM_'+self.environment.upper().replace('-', '_')+'_OFFLINE_CLEANUP':
                    'simulate-reviewed-'+self.environment+'-'+self.phase+'-once'}
        validate_confirmations(confirmations, self.environment, required)
        self._clocks(approval, current)
        inputs, scope, state = (json_object(artifacts[k])
                                for k in ('inputs', 'scope', 'state'))
        require(inputs.get('environment') == self.environment
                and inputs.get('region') == 'us-east-1'
                and isinstance(inputs.get('account'), str)
                and re.fullmatch('[0-9]{12}', inputs['account'])
                and isinstance(inputs.get('cluster'), str)
                and inputs['cluster'].endswith('-'+self.environment.removeprefix('aws-'))
                and _budget(inputs.get('budget_limit_usd')) ==
                    _budget(approval.get('budget_limit_usd')),
                'cleanup-simulation-input-scope')
        state_addresses(state)
        require(scope.get('environment') == self.environment
                and scope.get('phase') == self.phase,
                'cleanup-simulation-review-scope')
        completed = _receipt_prefix(scope, self.environment, self.phase)
        return approval, inputs, scope, state, completed

    def _observe(self, raw: bytes, inputs: dict, approval: dict,
                 state_raw: bytes, current: str, *, cleanup_gate=None) -> dict:
        value = json_object(raw)
        require(value.get('identity') == {k: inputs[k]
                for k in ('environment', 'region', 'account', 'cluster')}
                and value.get('main') == self.main
                and value.get('state_sha256') == sha(state_raw)
                and value.get('inventory_complete') is True,
                'cleanup-simulation-observation-scope')
        validate_observation_age(value.get('observed_at'), current, ttl_seconds=60)
        require(_budget(value.get('estimated_total_usd')) <=
                _budget(approval['budget_limit_usd']), 'cleanup-simulation-budget')
        if cleanup_gate is not None:
            validate_cleanup_step(cleanup_gate, self.phase, value.get('cleanup'))
        return value

    def _journal(self, directory: Path, artifacts: dict[str, bytes],
                 approval_raw: bytes, timestamp: str) -> AttemptJournal:
        binding = {'environment': self.environment, 'phase': self.phase,
                   'main': self.main, 'inputs_sha256': sha(artifacts['inputs']),
                   'state_sha256': sha(artifacts['state']),
                   'proof_sha256': sha(approval_raw),
                   'scope_sha256': sha(artifacts['scope'])}
        return AttemptJournal.reserve(directory, binding, timestamp,
                                      repository_root=self.repository_root)

    @staticmethod
    def _result(raw: bytes) -> bool:
        result = json_object(raw)
        require(type(result.get('success')) is bool,
                'cleanup-simulation-unknown-call-result')
        return result['success']

    def _mutating_objects(self, artifacts, approval_raw, expected_sha, directory,
                          confirmations, transport, clock, approval, inputs, scope,
                          state, completed, immediate):
        objects = scope.get('objects')
        require(isinstance(objects, list) and bool(objects),
                'cleanup-simulation-object-set')
        objects = [_object(v) for v in objects]
        if self.phase == 'delete-business-namespaces':
            require(all(v['kind'] == 'Namespace' and v['name'] in BUSINESS_NAMESPACES
                        and v['deletion_requested'] is False for v in objects)
                    and len({v['name'] for v in objects}) == len(objects),
                    'cleanup-business-namespace-scope')
        else:
            require(all(v['kind'] in ('NodePool', 'EC2NodeClass')
                        and v['deletion_requested'] is False for v in objects)
                    and {v['kind'] for v in objects} == {'NodePool', 'EC2NodeClass'},
                    'cleanup-node-config-scope')
        require(immediate.get('objects') == objects,
                'cleanup-simulation-object-drift')
        now = clock.current(); self._clocks(approval, now)
        handle = self._journal(directory, artifacts, approval_raw, now)
        attempted = False
        try:
            remaining = list(objects)
            for index, obj in enumerate(objects):
                operation = 'delete-object-'+str(index).zfill(4)
                before = self._observe(transport.observe('object-'+str(index).zfill(4)+'-pre'),
                    inputs, approval, artifacts['state'], clock.current(), cleanup_gate=completed)
                require(before.get('objects') == remaining,
                        'cleanup-simulation-object-precondition')
                now = clock.current(); self._clocks(approval, now)
                handle.before(operation, now)
                now = clock.current(); self._clocks(approval, now)
                validate_observation_age(before['observed_at'], now, ttl_seconds=60)
                attempted = True
                if not self._result(transport.mutate(operation, sha(canonical(obj)))):
                    handle.failure(operation, clock.current())
                    raise RuleViolation('cleanup-simulation-explicit-call-failure')
                after = self._observe(transport.observe('object-'+str(index).zfill(4)+'-post'),
                    inputs, approval, artifacts['state'], clock.current())
                self._deadline(approval, clock.current())
                remaining = remaining[1:]
                require(after.get('objects') == remaining,
                        'cleanup-simulation-object-postcondition')
                handle.success(operation, self._deadline_now(approval, clock))
            final = self._observe(transport.observe('post'), inputs, approval,
                                  artifacts['state'], clock.current())
            self._deadline(approval, clock.current())
            require(final.get('objects') == [] and final.get('state_unchanged') is True,
                    'cleanup-simulation-final-object-postcondition')
            operations = tuple('delete-object-'+str(i).zfill(4)
                               for i in range(len(objects)))
            handle.complete(operations, self._deadline_now(approval, clock))
            snapshot = handle.snapshot()
            return self._success(handle, snapshot, len(objects), 0)
        except CleanupSimulationStopped:
            raise
        except Exception:
            raise CleanupSimulationStopped('object-cleanup', attempted) from None
        finally:
            handle.close()

    def _read_only_drain(self, artifacts, approval_raw, directory, transport,
                         clock, approval, inputs, scope, completed, immediate):
        if self.phase == 'drain-external-secrets':
            expected = scope.get('external_secrets')
            require(isinstance(expected, list), 'cleanup-external-secret-set')
            expected = [_external_secret(v) for v in expected]
            require(immediate.get('external_secrets') == expected,
                    'cleanup-external-secret-drift')
            if expected:
                require(all(v['deletion_requested'] for v in expected),
                        'cleanup-external-secret-not-deleting')
                return {'status': 'offline-cleanup-stage-waiting',
                        'environment': self.environment, 'phase': self.phase,
                        'simulation_only': True, 'remaining_count': len(expected),
                        'journal_reserved': False, 'simulated_call_attempted': False,
                        'live_execution_authorized': False}
        else:
            counts = immediate.get('runtime_remaining_counts')
            require(isinstance(counts, dict) and set(counts) == set(RUNTIME_KEYS)
                    and all(type(v) is int and v >= 0 for v in counts.values()),
                    'cleanup-runtime-counts')
            if any(counts.values()):
                return {'status': 'offline-cleanup-stage-waiting',
                        'environment': self.environment, 'phase': self.phase,
                        'simulation_only': True, 'remaining_count': sum(counts.values()),
                        'journal_reserved': False, 'simulated_call_attempted': False,
                        'live_execution_authorized': False}
        now = clock.current(); self._clocks(approval, now)
        handle = self._journal(directory, artifacts, approval_raw, now)
        try:
            now = clock.current(); self._clocks(approval, now)
            handle.observed_absent(self.phase, now)
            final = self._observe(transport.observe('post'), inputs, approval,
                                  artifacts['state'], clock.current())
            self._deadline(approval, clock.current())
            if self.phase == 'drain-external-secrets':
                require(final.get('external_secrets') == [],
                        'cleanup-external-secret-postcondition')
            else:
                require(final.get('runtime_remaining_counts') ==
                        {k: 0 for k in RUNTIME_KEYS}, 'cleanup-runtime-postcondition')
            require(final.get('state_unchanged') is True,
                    'cleanup-state-postcondition')
            handle.complete((self.phase,), self._deadline_now(approval, clock))
            return self._success(handle, handle.snapshot(), 0, 1)
        except Exception:
            raise CleanupSimulationStopped('read-only-drain-confirmation', False) from None
        finally:
            handle.close()

    def _eni_sg(self, artifacts, approval_raw, directory, transport, clock,
                approval, inputs, scope, completed, immediate):
        captured_eni, captured_sg = scope.get('captured_eni'), scope.get('captured_sg')
        network = _network_scope(scope.get('network_scope'))
        now = clock.current(); self._clocks(approval, now)
        handle = self._journal(directory, artifacts, approval_raw, now)
        attempted = False
        try:
            eni = immediate
            decision = eni_decision(captured_eni, eni.get('current_eni'),
                eni.get('interfaces_by_group'), network, attempted=False,
                group_present=eni.get('group_present'))
            if decision == 'confirmed-absent':
                handle.observed_absent('delete-captured-eni',
                                       self._deadline_now(approval, clock))
                sg_source = eni
            else:
                now = clock.current(); self._clocks(approval, now)
                handle.before('delete-captured-eni', now)
                now = clock.current(); self._clocks(approval, now)
                validate_observation_age(eni['observed_at'], now, ttl_seconds=60)
                attempted = True
                if not self._result(transport.mutate('delete-captured-eni',
                                                     sha(canonical(captured_eni)))):
                    handle.failure('delete-captured-eni', clock.current())
                    raise RuleViolation('cleanup-simulation-explicit-call-failure')
                sg_source = self._observe(transport.observe('eni-post'), inputs,
                    approval, artifacts['state'], clock.current())
                self._deadline(approval, clock.current())
                require(eni_decision(captured_eni, sg_source.get('current_eni'),
                    sg_source.get('interfaces_by_group'), network, attempted=True,
                    group_present=sg_source.get('group_present')) == 'confirmed-absent',
                    'cleanup-eni-postcondition')
                handle.success('delete-captured-eni',
                               self._deadline_now(approval, clock))
            decision = sg_decision(captured_sg, sg_source.get('current_sg'),
                sg_source.get('groups_in_vpc'), sg_source.get('interfaces_for_sg'),
                network, attempted=False)
            if decision == 'confirmed-absent':
                handle.observed_absent('delete-captured-sg',
                                       self._deadline_now(approval, clock))
            else:
                now = clock.current(); self._clocks(approval, now)
                handle.before('delete-captured-sg', now)
                now = clock.current(); self._clocks(approval, now)
                validate_observation_age(sg_source['observed_at'], now, ttl_seconds=60)
                attempted = True
                if not self._result(transport.mutate('delete-captured-sg',
                                                     sha(canonical(captured_sg)))):
                    handle.failure('delete-captured-sg', clock.current())
                    raise RuleViolation('cleanup-simulation-explicit-call-failure')
                after = self._observe(transport.observe('sg-post'), inputs, approval,
                                      artifacts['state'], clock.current())
                self._deadline(approval, clock.current())
                require(sg_decision(captured_sg, after.get('current_sg'),
                    after.get('groups_in_vpc'), after.get('interfaces_for_sg'),
                    network, attempted=True) == 'confirmed-absent',
                    'cleanup-sg-postcondition')
                handle.success('delete-captured-sg',
                               self._deadline_now(approval, clock))
            final = self._observe(transport.observe('post'), inputs, approval,
                                  artifacts['state'], clock.current())
            self._deadline(approval, clock.current())
            require(final.get('current_eni') is None and final.get('current_sg') is None
                    and final.get('interfaces_by_group') == []
                    and final.get('groups_in_vpc') == []
                    and final.get('interfaces_for_sg') == []
                    and final.get('state_unchanged') is True,
                    'cleanup-network-final-postcondition')
            handle.complete(('delete-captured-eni', 'delete-captured-sg'),
                            self._deadline_now(approval, clock))
            return self._success(handle, handle.snapshot(),
                                 sum(c[0] == 'fake-mutate' for c in transport.calls), 0)
        except Exception:
            raise CleanupSimulationStopped('eni-sg-cleanup', attempted) from None
        finally:
            handle.close()

    def _success(self, handle, snapshot, mutations, absences):
        return {'status': 'offline-cleanup-stage-simulation-complete',
                'version': VERSION, 'environment': self.environment,
                'phase': self.phase, 'simulation_only': True,
                'simulated_mutation_count': mutations,
                'observed_absence_count': absences,
                'journal_marker_sha256': handle.marker_sha256,
                'journal_events_sha256': snapshot['events_sha256'],
                'kubernetes_mutation_executed': False,
                'aws_mutation_executed': False,
                'terraform_command_executed': False,
                'automatic_retry_performed': False,
                'live_execution_authorized': False, 'prod_qualified': False}

    def run(self, artifacts: dict[str, bytes], approval_raw: bytes,
            expected_approval_sha256: str, *, journal_directory: Path,
            confirmations: dict, transport: CleanupScenarioTransport,
            clock: ScenarioClock) -> dict:
        require(type(transport) is CleanupScenarioTransport
                and type(clock) is ScenarioClock, 'fixed-cleanup-fake-only')
        stage, attempted = 'local-inputs', False
        try:
            artifacts = dict(artifacts)
            approval, inputs, scope, state, completed = self._inputs(
                artifacts, approval_raw, expected_approval_sha256,
                journal_directory, confirmations, clock.current())
            stage = 'pre-observation'
            self._observe(transport.observe('pre'), inputs, approval,
                          artifacts['state'], clock.current(), cleanup_gate=completed)
            stage = 'immediate-observation'
            immediate = self._observe(transport.observe('immediate'), inputs, approval,
                artifacts['state'], clock.current(), cleanup_gate=completed)
            self._inputs(artifacts, approval_raw, expected_approval_sha256,
                         journal_directory, confirmations, clock.current())
            if self.phase in ('drain-external-secrets', 'drain-runtime'):
                return self._read_only_drain(artifacts, approval_raw, journal_directory,
                    transport, clock, approval, inputs, scope, completed, immediate)
            if self.phase in ('delete-business-namespaces', 'delete-node-config'):
                return self._mutating_objects(artifacts, approval_raw,
                    expected_approval_sha256, journal_directory, confirmations,
                    transport, clock, approval, inputs, scope, state, completed, immediate)
            return self._eni_sg(artifacts, approval_raw, journal_directory, transport,
                                clock, approval, inputs, scope, completed, immediate)
        except CleanupSimulationStopped:
            raise
        except Exception:
            raise CleanupSimulationStopped(stage, attempted) from None
