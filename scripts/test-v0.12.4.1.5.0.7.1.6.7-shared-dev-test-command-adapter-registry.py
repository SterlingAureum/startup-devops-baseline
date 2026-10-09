#!/usr/bin/env python3
"""Offline tests for the closed shared dev/test command-adapter registry."""

from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import unittest

import aws_two_wave_teardown_command_registry as REGISTRY
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.7-shared-dev-test-command-adapter-registry"
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())


def operation_request(environment: str, phase: str, index: int) -> dict:
    spec = DRIVERS.phase_driver_spec(environment, phase)
    return DRIVERS._operation_request(
        spec=spec,
        spec_sha256=REQUEST.sha256(spec),
        execution_request_sha256="a" * 64,
        operation_id=spec["operationIds"][index],
        operation_index=index,
    )


def mutate(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, list):
        return list(reversed(value)) if len(value) > 1 else value + ["changed"]
    return f"changed-{value}"


class CommandAdapterRegistryTests(unittest.TestCase):
    def test_registry_exactly_covers_reviewed_operations(self):
        registry = REGISTRY.command_registry()
        expected = {operation for values in DRIVERS.PHASE_OPERATIONS.values() for operation in values}
        self.assertEqual(set(REGISTRY.OPERATION_TRANSPORTS), expected)
        self.assertEqual(registry["operationIdCount"], 37)
        self.assertEqual(registry["phaseOperationCallCount"], 49)
        self.assertEqual(REGISTRY.command_registry_sha256(), FIXTURE["expectedCommandRegistrySha256"])
        self.assertEqual(REGISTRY.validate_command_registry(registry), registry)

    def test_transport_and_effect_counts_match_fixture(self):
        entries = REGISTRY.command_registry()["entries"]
        self.assertEqual(Counter(row["transportKind"] for row in entries), FIXTURE["transportKindCounts"])
        self.assertEqual(Counter(row["effectClass"] for row in entries), FIXTURE["effectClassCounts"])

    def test_every_entry_is_closed_and_has_one_adapter_identity(self):
        entries = REGISTRY.command_registry()["entries"]
        self.assertEqual(len({row["adapterId"] for row in entries}), 37)
        for row in entries:
            with self.subTest(operation=row["operationId"]):
                policy = REGISTRY.TRANSPORT_POLICIES[row["transportKind"]]
                self.assertEqual((row["effectClass"], row["timeoutSeconds"], row["outputPolicy"]), policy)
                self.assertTrue(row["allowedPhases"])
                self.assertFalse(row["rawCommandAccepted"])
                self.assertFalse(row["dynamicCommandTemplateAccepted"])
                self.assertFalse(row["credentialOrEndpointOverrideAccepted"])
                self.assertFalse(row["environmentFallbackAccepted"])
                self.assertFalse(row["automaticRetryAuthorized"])
                self.assertFalse(row["automaticRepairAuthorized"])
                self.assertFalse(row["implementedLive"])

    def test_reused_operations_bind_all_and_only_reviewed_phases(self):
        for operation in REGISTRY.OPERATION_TRANSPORTS:
            expected = [phase for phase, values in DRIVERS.PHASE_OPERATIONS.items() if operation in values]
            self.assertEqual(REGISTRY.adapter_entry(operation)["allowedPhases"], expected)
        self.assertEqual(len(REGISTRY.adapter_entry("verify-environment-context")["allowedPhases"]), 8)
        self.assertEqual(
            REGISTRY.adapter_entry("verify-empty-managed-state")["allowedPhases"],
            ["wave-two-apply", "final-read-only-audit"],
        )

    def test_operation_private_bindings_are_present_in_each_phase_spec(self):
        for operation in REGISTRY.OPERATION_TRANSPORTS:
            entry = REGISTRY.adapter_entry(operation)
            for phase in entry["allowedPhases"]:
                with self.subTest(operation=operation, phase=phase):
                    spec = DRIVERS.phase_driver_spec("aws-dev", phase)
                    self.assertTrue(set(entry["requiredPrivateBindings"]) <= set(spec["requiredPrivateBindings"]))

    def test_all_dev_test_phase_manifests_are_unique_and_valid(self):
        digests = set()
        for environment in ("aws-dev", "aws-test"):
            for phase, operations in DRIVERS.PHASE_OPERATIONS.items():
                with self.subTest(environment=environment, phase=phase):
                    manifest = REGISTRY.phase_command_manifest(environment, phase)
                    self.assertEqual(manifest["operationIds"], list(operations))
                    self.assertEqual(manifest["operationCount"], len(operations))
                    self.assertEqual(len(manifest["adapterEntrySha256s"]), len(operations))
                    self.assertEqual(
                        REGISTRY.validate_phase_command_manifest(manifest, environment=environment, phase=phase),
                        manifest,
                    )
                    digests.add(REQUEST.sha256(manifest))
        self.assertEqual(len(digests), 16)
        expected = REGISTRY.phase_command_manifest(FIXTURE["expectedEnvironment"], FIXTURE["expectedPhase"])
        self.assertEqual(REQUEST.sha256(expected), FIXTURE["expectedPhaseManifestSha256"])

    def test_dev_test_manifests_separate_environment_paths(self):
        dev = REGISTRY.phase_command_manifest("aws-dev", "wave-one-plan")
        test = REGISTRY.phase_command_manifest("aws-test", "wave-one-plan")
        for key in ("environment", "stateKey", "phaseDriverSpecSha256", "terraformRootRelativePath", "backendConfigRelativePath"):
            self.assertNotEqual(dev[key], test[key])
        for key in set(dev) - {"environment", "stateKey", "phaseDriverSpecSha256", "terraformRootRelativePath", "backendConfigRelativePath"}:
            self.assertEqual(dev[key], test[key])

    def test_prod_and_unknown_operations_are_rejected(self):
        with self.assertRaises(TeardownGateError):
            REGISTRY.phase_command_manifest("aws-prod", "wave-one-plan")
        with self.assertRaises(TeardownGateError):
            REGISTRY.adapter_entry("arbitrary-command")

    def test_every_registry_top_level_mutation_is_rejected(self):
        original = REGISTRY.command_registry()
        for key in original:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = mutate(changed[key])
                with self.assertRaises(TeardownGateError):
                    REGISTRY.validate_command_registry(changed)

    def test_every_manifest_top_level_mutation_is_rejected(self):
        original = REGISTRY.phase_command_manifest("aws-dev", "wave-one-plan")
        for key in original:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = mutate(changed[key])
                with self.assertRaises(TeardownGateError):
                    REGISTRY.validate_phase_command_manifest(changed, environment="aws-dev", phase="wave-one-plan")

    def test_all_reviewed_operation_requests_in_both_environments_select_exact_entries(self):
        selected = 0
        for environment in ("aws-dev", "aws-test"):
            for phase, operations in DRIVERS.PHASE_OPERATIONS.items():
                for index, operation in enumerate(operations):
                    with self.subTest(environment=environment, phase=phase, operation=operation):
                        result = REGISTRY.validate_operation_request_for_adapter(operation_request(environment, phase, index))
                        self.assertEqual(result["operationId"], operation)
                        self.assertEqual(result["adapterEntry"], REGISTRY.adapter_entry(operation))
                        self.assertFalse(result["liveBackendAvailable"])
                        self.assertFalse(result["liveCommandExecuted"])
                        selected += 1
        self.assertEqual(selected, 98)

    def test_cross_phase_or_reordered_operation_is_rejected(self):
        value = operation_request("aws-dev", "wave-one-plan", 0)
        value["operationId"] = "apply-exact-wave-one-saved-plan"
        with self.assertRaises(TeardownGateError):
            REGISTRY.validate_operation_request_for_adapter(value)
        value = operation_request("aws-dev", "wave-one-plan", 1)
        value["operationIndex"] = 2
        with self.assertRaises(TeardownGateError):
            REGISTRY.validate_operation_request_for_adapter(value)

    def test_operation_request_identity_and_authority_mutations_are_rejected(self):
        original = operation_request("aws-dev", "wave-one-plan", 2)
        mutations = {
            "schemaVersion": "changed",
            "environment": "aws-test",
            "stateKey": "changed",
            "phase": "wave-two-plan",
            "requestedAuthority": "changed",
            "executionSpecSha256": "0" * 64,
            "executionRequestSha256": "bad",
            "operationCount": 8,
            "simulationOnly": False,
            "liveCommandAuthorized": True,
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                with self.assertRaises(TeardownGateError):
                    REGISTRY.validate_operation_request_for_adapter(changed)

    def test_extra_operation_request_field_is_rejected(self):
        value = operation_request("aws-dev", "wave-one-plan", 0)
        value["command"] = "arbitrary"
        with self.assertRaises(TeardownGateError):
            REGISTRY.validate_operation_request_for_adapter(value)


if __name__ == "__main__":
    unittest.main()
