"""Versioned offline destroy-stage composition; fixed fake transport only.

No SDK, CLI, subprocess, network or live entry point. Simulation approval is a
fixture contract, never cloud authorization. Native facts are scripted test data.
"""
from __future__ import annotations
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from guarded_runtime_rules import (RuleViolation, require, json_object, validate_confirmations,
    validate_window, validate_proof, validate_observation_age, state_addresses, parse_utc)
from guarded_cleanup_rules import CLEANUP_STEPS, validate_cleanup_step
from guarded_plan_rules import managed_inventory, validate_destroy_plan
from guarded_attempt_journal import AttemptJournal

VERSION = 'v0.11.9.3.6.7.7.4'
COMMON_MODULES = ('cnpg_backup','eks','external_secrets','karpenter','tls_dns','vpc')
PROFILES = {
    'aws-dev': COMMON_MODULES+('fis','github_actions_runtime_identity'),
    'aws-test': COMMON_MODULES+('fis','github_actions_runtime_identity'),
    'aws-prod': COMMON_MODULES,
}
DEPENDENCY_MODULES = ('eks','cnpg_backup','external_secrets','karpenter','github_actions_runtime_identity')
ARTIFACT_KEYS = {'inputs','scope','state','plan','binary','text','provider_lock'}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class SimulationStopped(RuleViolation):
    def __init__(self, stage: str, attempted: bool):
        super().__init__('offline-stage-simulation-stopped')
        self.report = {'status':'offline-stage-simulation-stopped','stage':stage,
            'simulation_only':True,'simulated_call_attempted':attempted,
            'cloud_mutation_executed':False,'terraform_command_executed':False,
            'automatic_retry_performed':False,'preserve_private_evidence':True}


class ScenarioClock:
    """Scripted UTC samples; no system clock fallback."""
    def __init__(self, samples: tuple[str, ...]):
        require(isinstance(samples,tuple) and bool(samples), 'simulation-clock-required')
        self.samples=list(samples);self.last=None
    def current(self) -> str:
        require(bool(self.samples),'simulation-clock-exhausted')
        value=self.samples.pop(0);instant=parse_utc(value)
        require(self.last is None or instant>=self.last,'simulation-clock-regression')
        self.last=instant
        return value


class ScenarioTransport:
    """Records fixed fake observations and a fake apply hash; cannot run commands."""
    def __init__(self, observations: dict[str, bytes], apply_result: bytes, *, fail_at: str = ''):
        self.observations=dict(observations);self.apply_result=apply_result
        self.fail_at=fail_at;self.calls=[]
    def observe(self, label: str) -> bytes:
        require(label in ('pre','immediate','post'), 'simulation-observation-label')
        self.calls.append(('observe',label))
        require(self.fail_at != label and label in self.observations,'simulation-observation-failed')
        return self.observations[label]
    def apply(self, binary: bytes) -> bytes:
        self.calls.append(('fake-apply',sha(binary)))
        require(self.fail_at != 'apply','simulation-call-uncertain')
        return self.apply_result


def _module_name(module: str) -> str:
    match=re.fullmatch(r'module\.([A-Za-z_][A-Za-z0-9_]*)(?:\[[0-9]+\])?',module)
    require(match is not None,'simulation-module-profile')
    return match[1]


def _budget(value) -> Decimal:
    require(isinstance(value,str) and re.fullmatch(r'[0-9]+\.[0-9]{2}',value),'simulation-budget-schema')
    try: parsed=Decimal(value)
    except InvalidOperation: raise RuleViolation('simulation-budget-schema') from None
    require(parsed.is_finite() and parsed > 0,'simulation-budget-schema')
    return parsed


class OfflineDestroyAdapter:
    """Same composition for three explicit profiles and two narrow phases.

    The approved journal path and hashes are pinned before observations. The fake
    call is blocked until clocks, fresh scope, cleanup dependencies and plan pass.
    No historical adapter is imported or changed by this class.
    """
    def __init__(self, environment: str, phase: str, main: str, *, repository_root: Path):
        require(isinstance(environment,str) and environment in PROFILES,'simulation-explicit-environment')
        require(phase in ('eks-delete','final-delete'),'simulation-phase')
        require(isinstance(main,str) and re.fullmatch('[0-9a-f]{40}',main),'simulation-main-format')
        self.environment,self.phase,self.main=environment,phase,main
        self.repository_root=Path(repository_root)

    def _clocks(self, approval: dict, current: str):
        validate_window(approval['start_utc'],approval['end_utc'],current,
                        maximum_seconds=28800,minimum_remaining_seconds=60)
        validate_proof(approval['created_at'],approval['expires_at'],current,approval['end_utc'],
                       ttl_seconds=900,original_created=approval['original_created_at'])

    def _inputs(self, artifacts: dict, approval_raw: bytes, expected_approval_sha256: str,
                journal_directory: Path, confirmations: dict, current: str):
        require(isinstance(artifacts,dict) and set(artifacts)==ARTIFACT_KEYS
                and all(isinstance(x,bytes) for x in artifacts.values()) and bool(artifacts['binary']),
                'simulation-artifacts')
        require(isinstance(approval_raw,bytes) and sha(approval_raw)==expected_approval_sha256,
                'simulation-reviewed-approval-drift')
        approval=json_object(approval_raw)
        require(approval.get('schema')=='offline-destroy-approval-v1'
                and approval.get('simulation_only') is True
                and approval.get('environment')==self.environment and approval.get('phase')==self.phase
                and approval.get('main')==self.main,'simulation-approval-scope')
        require(approval.get('hashes')=={k:sha(v) for k,v in artifacts.items()},'simulation-artifact-drift')
        require(isinstance(approval.get('journal_directory'),str)
                and Path(journal_directory).is_absolute()
                and str(journal_directory)==approval['journal_directory'],'simulation-journal-path-drift')
        required={'CONFIRM_'+self.environment.upper().replace('-','_')+'_OFFLINE_DESTROY':
                  'simulate-reviewed-'+self.environment+'-'+self.phase+'-once'}
        validate_confirmations(confirmations,self.environment,required)
        self._clocks(approval,current)
        inputs,scope,state,plan=(json_object(artifacts[k]) for k in ('inputs','scope','state','plan'))
        require(inputs.get('environment')==self.environment and inputs.get('region')=='us-east-1'
                and isinstance(inputs.get('account'),str) and re.fullmatch('[0-9]{12}',inputs['account'])
                and isinstance(inputs.get('cluster'),str)
                and inputs['cluster'].endswith('-'+self.environment.removeprefix('aws-')),'simulation-input-scope')
        require(isinstance(inputs.get('terraform_version'),str)
                and re.fullmatch(r'1\.[0-9]+\.[0-9]+',inputs['terraform_version'])
                and inputs.get('workspace')=='default'
                and plan.get('terraform_version')==inputs['terraform_version'], 'simulation-terraform-binding')
        require(scope.get('environment')==self.environment and scope.get('phase')==self.phase,
                'simulation-review-scope')
        require(_budget(inputs.get('budget_limit_usd'))==_budget(approval.get('budget_limit_usd')),
                'simulation-budget-binding')
        receipts=scope.get('receipts');require(isinstance(receipts,list),'simulation-receipts')
        completed=[]
        for row in receipts:
            require(isinstance(row,dict) and set(row)=={'step','raw','sha256'}
                    and isinstance(row['raw'],str) and sha(row['raw'].encode())==row['sha256'],
                    'simulation-receipt-drift')
            receipt=json_object(row['raw'].encode())
            require(receipt.get('environment')==self.environment and receipt.get('step')==row['step']
                    and receipt.get('confirmed') is True and receipt.get('simulation_only') is True,
                    'simulation-unconfirmed-receipt')
            completed.append(row['step'])
        require(tuple(completed)==CLEANUP_STEPS[:len(completed)]
                and len(completed)<len(CLEANUP_STEPS) and CLEANUP_STEPS[len(completed)]==self.phase,
                'simulation-receipt-prefix')
        reviewed=scope.get('reviewed_resources');absence=scope.get('reviewed_remote_absence')
        require(isinstance(reviewed,list) and isinstance(absence,list),'simulation-plan-review-schema')
        inventory=managed_inventory(state)
        for row in inventory.values():
            require(_module_name(row['module']) in PROFILES[self.environment],'simulation-environment-module')
        if self.phase=='eks-delete':
            require(all(isinstance(row,dict) and isinstance(row.get('module'),str)
                        and _module_name(row['module']) in DEPENDENCY_MODULES for row in reviewed),
                    'simulation-eks-dependency-scope')
            required_eks={a for a,r in inventory.items() if _module_name(r['module'])=='eks' or r['type'].startswith('aws_eks_')}
            require(any(r['type']=='aws_eks_cluster' for r in inventory.values())
                    and required_eks<={row.get('address') for row in reviewed},'simulation-eks-coverage')
        gate=validate_destroy_plan(plan,state,tuple(reviewed),final=self.phase=='final-delete',
                                   reviewed_remote_absence=tuple(absence))
        return approval,inputs,scope,state,plan,tuple(completed),gate

    def _observation(self, raw: bytes, inputs: dict, approval: dict, artifacts: dict,
                     completed: tuple[str,...], scope: dict, current: str, *, post=False):
        observation=json_object(raw)
        require(observation.get('identity')=={k:inputs[k] for k in ('environment','region','account','cluster')}
                and observation.get('main')==self.main,'simulation-observation-identity')
        require(observation.get('inventory_complete') is True,'simulation-incomplete-inventory')
        validate_observation_age(observation.get('observed_at'),current,ttl_seconds=60)
        require(_budget(observation.get('estimated_total_usd'))<=_budget(approval['budget_limit_usd']),
                'simulation-estimate-over-budget')
        if not post:
            require(observation.get('state_sha256')==sha(artifacts['state'])
                    and observation.get('plan_sha256')==sha(artifacts['plan'])
                    and observation.get('binary_sha256')==sha(artifacts['binary'])
                    and observation.get('text_sha256')==sha(artifacts['text'])
                    and observation.get('provider_lock_sha256')==sha(artifacts['provider_lock'])
                    and observation.get('terraform_version')==inputs['terraform_version']
                    and observation.get('workspace')==inputs['workspace']
                    and observation.get('native_remote_absence')==scope['reviewed_remote_absence'],
                    'simulation-fresh-input-or-absence-drift')
            validate_cleanup_step(completed,self.phase,observation.get('cleanup'))
        return observation

    def run(self, artifacts: dict[str,bytes], approval_raw: bytes, expected_approval_sha256: str, *,
            journal_directory: Path, confirmations: dict, transport: ScenarioTransport, clock: ScenarioClock) -> dict:
        require(type(transport) is ScenarioTransport and type(clock) is ScenarioClock,'fixed-offline-transport-only')
        # Snapshot immutable bytes, not caller-edited counters or mutable plan dicts.
        stage='local-inputs';attempted=False;handle=None
        try:
            require(isinstance(artifacts,dict),'simulation-artifacts')
            artifacts=dict(artifacts)
            current=clock.current()
            approval,inputs,scope,state,plan,completed,gate=self._inputs(artifacts,approval_raw,
                expected_approval_sha256,journal_directory,confirmations,current)
            stage='pre-observation'
            self._observation(transport.observe('pre'),inputs,approval,artifacts,completed,scope,clock.current())
            binding={'environment':self.environment,'phase':self.phase,'main':self.main,
                     'inputs_sha256':sha(artifacts['inputs']),'state_sha256':sha(artifacts['state']),
                     'proof_sha256':sha(approval_raw),'scope_sha256':sha(artifacts['scope'])}
            stage='reserve-journal'
            current=clock.current();self._clocks(approval,current)
            handle=AttemptJournal.reserve(journal_directory,binding,current,repository_root=self.repository_root)
            stage='immediate-observation'
            immediate_raw=transport.observe('immediate')
            self._observation(immediate_raw,inputs,approval,artifacts,completed,scope,clock.current())
            stage='final-pre-call-gates';current=clock.current()
            self._inputs(artifacts,approval_raw,expected_approval_sha256,journal_directory,confirmations,current)
            self._observation(immediate_raw,inputs,approval,artifacts,completed,scope,current)
            stage='intent-barrier';handle.before('apply-saved-plan',current)
            stage='post-barrier-gates';current=clock.current()
            self._clocks(approval,current)
            self._observation(immediate_raw,inputs,approval,artifacts,completed,scope,current)
            stage='fake-saved-plan-call';attempted=True
            result=json_object(transport.apply(artifacts['binary']))
            require(type(result.get('success')) is bool,'simulation-unknown-call-result')
            if result.get('success') is not True:
                handle.failure('apply-saved-plan',clock.current())
                raise RuleViolation('simulation-explicit-call-failure')
            stage='post-observation';current=clock.current()
            # Execution deadline also applies after an accepted fake call; expired proof cannot authorize another call.
            require(current<=approval['end_utc'],'simulation-execution-deadline')
            observation=self._observation(transport.observe('post'),inputs,approval,artifacts,completed,scope,current,post=True)
            selected=set(gate['deleted'])|set(gate['drift']);native=observation.get('native_absent_addresses')
            require(isinstance(native,list) and all(isinstance(x,str) for x in native)
                    and len(native)==len(set(native)) and set(native)==selected,'simulation-native-postcondition')
            after=observation.get('state_after');before_map=state_addresses(state);after_map=state_addresses(after)
            retained={a:r for a,r in managed_inventory(state).items() if a not in selected}
            require(managed_inventory(after)==retained,'simulation-retained-managed-drift')
            if self.phase=='eks-delete':
                require(after_map=={a:v for a,v in before_map.items() if a not in selected}
                        and observation.get('eks_absent') is True,'simulation-eks-postcondition')
            else:
                require(all(a in before_map and before_map[a]==v and v[0]=='data' for a,v in after_map.items())
                        and observation.get('final_cloud_absent') is True,'simulation-final-postcondition')
            stage='confirmed-outcome';handle.success('apply-saved-plan',current)
            handle.complete(('apply-saved-plan',),current)
            snapshot=handle.snapshot()
            return {'status':'offline-destroy-stage-simulation-complete','version':VERSION,
                'environment':self.environment,'phase':self.phase,'main':self.main,'simulation_only':True,
                'managed_delete_count':gate['managed_delete_count'],
                'reviewed_remote_absence_count':gate['reviewed_remote_absence_count'],
                'journal_marker_sha256':handle.marker_sha256,'journal_events_sha256':snapshot['events_sha256'],
                'cloud_mutation_executed':False,'terraform_command_executed':False,
                'automatic_retry_performed':False,'live_execution_authorized':False,'prod_qualified':False}
        except Exception:
            # Unknown call/postcondition errors preserve pending; never infer success or retry.
            raise SimulationStopped(stage,attempted) from None
        finally:
            if handle is not None:handle.close()
