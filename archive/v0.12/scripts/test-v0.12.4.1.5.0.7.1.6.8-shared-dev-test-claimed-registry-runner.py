#!/usr/bin/env python3
"""Offline tests for the claim-bound shared dev/test registry runner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import aws_two_wave_teardown_command_registry as REGISTRY
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_registry_runner as RUNNER


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.8-shared-dev-test-claimed-registry-runner"
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())
NOW = "2026-10-09T10:05:00Z"


def claim(environment: str = "aws-dev", phase: str = "wave-one-plan") -> dict:
    spec = DRIVERS.phase_driver_spec(environment, phase)
    return {
        "schemaVersion": DRIVERS.CLAIM_SCHEMA,
        "status": "approval-consumed-before-fixed-fake-phase-dispatch",
        "receiptSha256": "1" * 64,
        "approvalRecordSha256": "2" * 64,
        "executionRequestSha256": "3" * 64,
        "executionSpecSha256": REQUEST.sha256(spec),
        "environment": environment,
        "stateKey": spec["stateKey"],
        "phase": phase,
        "attemptNumber": 1,
        "controlPlaneCommit": "4" * 40,
        "requestedAuthority": spec["requestedAuthority"],
        "operationSetSha256": REQUEST.sha256(spec["operationIds"]),
        "operationCount": len(spec["operationIds"]),
        "claimedAtUtc": "2026-10-09T10:00:00Z",
        "expiresAtUtc": "2026-10-09T10:15:00Z",
        "oneAttemptOnly": True,
        "approvalConsumedByLease": True,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }


def bindings(value: dict) -> dict[str, str]:
    spec = DRIVERS.phase_driver_spec(value["environment"], value["phase"])
    result = {name: format(index + 10, "064x") for index, name in enumerate(spec["requiredPrivateBindings"])}
    for key in ("receiptSha256", "approvalRecordSha256", "executionRequestSha256"):
        result[key] = value[key]
    return result


def inputs(environment: str = "aws-dev", phase: str = "wave-one-plan") -> dict:
    value = claim(environment, phase)
    digest = REQUEST.sha256(value)
    return {
        "claim": value,
        "expected_claim_sha256": digest,
        "phase_command_manifest": REGISTRY.phase_command_manifest(environment, phase),
        "operation_requests": RUNNER.build_claimed_operation_requests(
            value,
            expected_claim_sha256=digest,
            now_utc=NOW,
        ),
        "private_bindings": bindings(value),
        "now_utc": NOW,
    }


class ClaimedRegistryRunnerTests(unittest.TestCase):
    def test_all_dev_test_phases_run_in_exact_reviewed_order(self):
        total = 0
        digests = set()
        for environment in ("aws-dev", "aws-test"):
            for phase, operations in DRIVERS.PHASE_OPERATIONS.items():
                with self.subTest(environment=environment, phase=phase):
                    backend = RUNNER.FixedFakeRegistryBackend()
                    result = RUNNER.run_claimed_registry_once(**inputs(environment, phase), backend=backend)
                    self.assertEqual([row["operationId"] for row in backend.calls], list(operations))
                    self.assertEqual(result["operationCallCount"], len(operations))
                    self.assertFalse(result["liveCommandExecuted"])
                    self.assertFalse(result["executionPerformed"])
                    digests.add(result["phaseCommandManifestSha256"])
                    total += len(backend.calls)
        self.assertEqual(total, 98)
        self.assertEqual(len(digests), 16)

    def test_fixture_result_digests_are_stable(self):
        backend = RUNNER.FixedFakeRegistryBackend()
        value = RUNNER.run_claimed_registry_once(**inputs(), backend=backend)
        self.assertEqual(value["claimSha256"], FIXTURE["expectedClaimSha256"])
        self.assertEqual(value["phaseCommandManifestSha256"], FIXTURE["expectedPhaseCommandManifestSha256"])
        self.assertEqual(value["operationManifestSha256"], FIXTURE["expectedOperationManifestSha256"])

    def test_claim_and_all_inputs_are_validated_before_first_backend_call(self):
        cases = []
        changed = inputs()
        changed["expected_claim_sha256"] = "0" * 64
        cases.append(changed)
        changed = inputs()
        changed["phase_command_manifest"]["operationIds"] = list(reversed(changed["phase_command_manifest"]["operationIds"]))
        cases.append(changed)
        changed = inputs()
        changed["operation_requests"] = list(reversed(changed["operation_requests"]))
        cases.append(changed)
        changed = inputs()
        changed["private_bindings"].pop("stateInventorySha256")
        cases.append(changed)
        for case in cases:
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.subTest(case=len(case)):
                with self.assertRaises(RUNNER.RegistryRunnerStopped) as stopped:
                    RUNNER.run_claimed_registry_once(**case, backend=backend)
                self.assertEqual(backend.calls, [])
                self.assertFalse(backend.used)
                self.assertEqual(stopped.exception.report["backendCallCount"], 0)

    def test_claim_digest_binds_every_top_level_field(self):
        original = inputs()
        for key in original["claim"]:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                value = changed["claim"][key]
                if isinstance(value, bool):
                    changed["claim"][key] = not value
                elif isinstance(value, int):
                    changed["claim"][key] = value + 1
                else:
                    changed["claim"][key] = f"changed-{value}"
                backend = RUNNER.FixedFakeRegistryBackend()
                with self.assertRaises(RUNNER.RegistryRunnerStopped):
                    RUNNER.run_claimed_registry_once(**changed, backend=backend)
                self.assertEqual(backend.calls, [])

    def test_claim_semantics_reject_expired_prod_and_live_flags(self):
        cases = []
        changed = inputs()
        changed["now_utc"] = "2026-10-09T10:15:00Z"
        cases.append(changed)
        changed = inputs()
        changed["claim"]["simulationOnly"] = False
        changed["expected_claim_sha256"] = REQUEST.sha256(changed["claim"])
        cases.append(changed)
        changed = inputs()
        changed["claim"]["automaticRetryAuthorized"] = True
        changed["expected_claim_sha256"] = REQUEST.sha256(changed["claim"])
        cases.append(changed)
        for case in cases:
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(RUNNER.RegistryRunnerStopped):
                RUNNER.run_claimed_registry_once(**case, backend=backend)
            self.assertEqual(backend.calls, [])
        prod = claim()
        prod["environment"] = "aws-prod"
        with self.assertRaises(Exception):
            RUNNER.validate_durable_phase_claim(prod, expected_claim_sha256=REQUEST.sha256(prod), now_utc=NOW)

    def test_operation_request_cross_phase_reorder_extra_and_mutation_stop_before_calls(self):
        cases = []
        changed = inputs()
        changed["operation_requests"][0]["operationId"] = "apply-exact-wave-one-saved-plan"
        cases.append(changed)
        changed = inputs()
        changed["operation_requests"][0]["phase"] = "wave-two-plan"
        cases.append(changed)
        changed = inputs()
        changed["operation_requests"][0]["command"] = "arbitrary"
        cases.append(changed)
        changed = inputs()
        changed["operation_requests"] = changed["operation_requests"][:-1]
        cases.append(changed)
        for case in cases:
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(RUNNER.RegistryRunnerStopped):
                RUNNER.run_claimed_registry_once(**case, backend=backend)
            self.assertEqual(backend.calls, [])

    def test_phase_bindings_are_exact_sha_only_and_claim_bound(self):
        cases = []
        changed = inputs()
        changed["private_bindings"]["extra"] = "a" * 64
        cases.append(changed)
        changed = inputs()
        changed["private_bindings"]["stateInventorySha256"] = "not-a-sha"
        cases.append(changed)
        changed = inputs()
        changed["private_bindings"]["receiptSha256"] = "f" * 64
        cases.append(changed)
        for case in cases:
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(RUNNER.RegistryRunnerStopped):
                RUNNER.run_claimed_registry_once(**case, backend=backend)
            self.assertEqual(backend.calls, [])

    def test_each_backend_call_receives_only_its_registered_binding_subset(self):
        value = inputs("aws-dev", "wave-one-plan")
        backend = RUNNER.FixedFakeRegistryBackend()
        RUNNER.run_claimed_registry_once(**value, backend=backend)
        for call, operation_id in zip(backend.calls, DRIVERS.PHASE_OPERATIONS["wave-one-plan"], strict=True):
            required = REGISTRY.adapter_entry(operation_id)["requiredPrivateBindings"]
            selected = {name: value["private_bindings"][name] for name in required}
            self.assertEqual(call["privateBindingSetSha256"], REQUEST.sha256(selected))

    def test_first_failed_operation_stops_without_later_calls(self):
        value = inputs("aws-dev", "wave-one-apply")
        operations = DRIVERS.PHASE_OPERATIONS["wave-one-apply"]
        backend = RUNNER.FixedFakeRegistryBackend(fail_at=operations[3])
        with self.assertRaises(RUNNER.RegistryRunnerStopped) as stopped:
            RUNNER.run_claimed_registry_once(**value, backend=backend)
        self.assertEqual([row["operationId"] for row in backend.calls], list(operations[:4]))
        self.assertEqual(stopped.exception.report["stage"], "fixed-fake-registry-operation-failed")
        self.assertEqual(stopped.exception.report["failedOperationId"], operations[3])
        self.assertTrue(stopped.exception.report["claimBound"])
        self.assertFalse(stopped.exception.report["automaticRetryPerformed"])

    def test_malformed_response_stops_without_later_calls(self):
        value = inputs("aws-test", "safe-residue-delete")
        operations = DRIVERS.PHASE_OPERATIONS["safe-residue-delete"]
        backend = RUNNER.FixedFakeRegistryBackend(malformed_at=operations[1])
        with self.assertRaises(RUNNER.RegistryRunnerStopped) as stopped:
            RUNNER.run_claimed_registry_once(**value, backend=backend)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(stopped.exception.report["stage"], "fixed-fake-registry-response-malformed")
        self.assertFalse(stopped.exception.report["liveCommandExecuted"])

    def test_backend_is_exact_type_and_single_use(self):
        class Lookalike(RUNNER.FixedFakeRegistryBackend):
            pass

        lookalike = Lookalike()
        with self.assertRaises(RUNNER.RegistryRunnerStopped):
            RUNNER.run_claimed_registry_once(**inputs(), backend=lookalike)
        backend = RUNNER.FixedFakeRegistryBackend()
        RUNNER.run_claimed_registry_once(**inputs(), backend=backend)
        with self.assertRaises(RUNNER.RegistryRunnerStopped) as stopped:
            RUNNER.run_claimed_registry_once(**inputs(), backend=backend)
        self.assertEqual(stopped.exception.report["backendCallCount"], 0)

    def test_result_and_stop_reports_are_redacted(self):
        result = RUNNER.run_claimed_registry_once(**inputs(), backend=RUNNER.FixedFakeRegistryBackend())
        failed_backend = RUNNER.FixedFakeRegistryBackend(fail_at="verify-environment-context")
        with self.assertRaises(RUNNER.RegistryRunnerStopped) as stopped:
            RUNNER.run_claimed_registry_once(**inputs(), backend=failed_backend)
        serialized = json.dumps([result, stopped.exception.report], sort_keys=True)
        for forbidden in ("arn:aws", "/home/", "vpc-", "sg-", "eni-"):
            self.assertNotIn(forbidden, serialized.lower())
        self.assertNotIn("private_bindings", serialized)
        self.assertNotIn("rawCommand", serialized)


if __name__ == "__main__":
    unittest.main()
