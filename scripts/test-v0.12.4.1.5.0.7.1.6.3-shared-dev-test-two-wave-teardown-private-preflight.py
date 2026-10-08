#!/usr/bin/env python3
"""Offline tests for guarded private teardown evidence and receipt boundaries."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

import aws_two_wave_teardown_private_preflight as PRIVATE


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown-private-preflight"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(ROOT / "scripts/preflight-v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown.py", "private_preflight_cli_under_test")
REQUEST = PRIVATE.REQUEST


class PrivatePreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())
        self.now = self.fixture["verificationClockUtc"]

    def phase_bundle(self, phase):
        if phase in ("controller-cleanup", "wave-one-plan", "wave-one-apply"):
            request = copy.deepcopy(self.fixture["devWaveOnePlan"]["request"])
            environment = "aws-dev"
            state_key = "environments/dev/terraform.tfstate"
        else:
            request = copy.deepcopy(self.fixture["testWaveTwoApply"]["request"])
            environment = "aws-test"
            state_key = "environments/test/terraform.tfstate"
        request["phase"] = phase
        request["expiresAtUtc"] = "2026-10-09T03:05:00Z" if phase in ("wave-one-apply", "wave-two-apply") else "2026-10-09T01:05:00Z"
        request["predecessorReceiptSha256"] = None if phase == "controller-cleanup" else "b" * 64
        request["reviewedPlan"] = None
        request["safeResidue"] = None

        if phase == "controller-cleanup":
            facts = {
                "controllerInventorySha256": "d" * 64,
                "controllerOwnedResourceCount": 3,
                "reconciliationTargetBound": True,
                "backupDeletionRequested": True,
            }
        elif phase == "wave-one-plan":
            facts = {
                "stateSnapshotSha256": "d" * 64,
                "historySnapshotSha256": "e" * 64,
                "sourceManifestSha256": "f" * 64,
                "networkAddressCount": 2,
                "nonNetworkAddressCount": 2,
            }
        elif phase == "wave-one-apply":
            request["reviewedPlan"] = {
                "wave": "non-network",
                "binaryPlanSha256": "d" * 64,
                "planRecordSha256": "e" * 64,
                "humanReviewed": True,
                "managedDeleteCount": 2,
                "planReviewExpiresAtUtc": "2026-10-09T04:00:00Z",
            }
            facts = self.apply_facts(2)
        elif phase == "post-wave-one-inventory":
            request["reviewedPlan"] = None
            facts = {
                "stateSnapshotSha256": "d" * 64,
                "historySnapshotSha256": "e" * 64,
                "eksAbsent": True,
                "networkAddressCount": 2,
                "nonNetworkAddressCount": 0,
            }
        elif phase == "safe-residue-delete":
            request["reviewedPlan"] = None
            request["safeResidue"] = {
                "category": "orphan-eks-cluster-security-group",
                "identitySha256": "f" * 64,
                "exactBound": True,
                "deletionAuthorized": False,
            }
            facts = {
                "dependencyInventorySha256": "a" * 64,
                "residueCategory": "orphan-eks-cluster-security-group",
                "residueIdentitySha256": "f" * 64,
                "exactBound": True,
                "deletionAlreadyAttempted": False,
            }
        elif phase == "wave-two-plan":
            request["reviewedPlan"] = None
            facts = {
                "stateSnapshotSha256": "d" * 64,
                "historySnapshotSha256": "e" * 64,
                "dependencyInventorySha256": "a" * 64,
                "safeResidueCount": 0,
                "unknownDependencyCount": 0,
                "controllerOwnedDependencyCount": 0,
            }
        elif phase == "wave-two-apply":
            request["reviewedPlan"] = {
                "wave": "network",
                "binaryPlanSha256": "d" * 64,
                "planRecordSha256": "e" * 64,
                "humanReviewed": True,
                "managedDeleteCount": 2,
                "planReviewExpiresAtUtc": "2026-10-09T04:00:00Z",
            }
            facts = self.apply_facts(2)
        elif phase == "final-read-only-audit":
            request["reviewedPlan"] = None
            request["state"].update(managedAddressCount=0, networkAddressCount=0, nonNetworkAddressCount=0)
            facts = {
                "finalStateSha256": "d" * 64,
                "absenceInventorySha256": "e" * 64,
                "historySnapshotSha256": "f" * 64,
                "managedStateAddressCount": 0,
                "protectedFoundationPreserved": True,
            }
        else:
            raise AssertionError(phase)

        evidence = {
            "schemaVersion": PRIVATE.EVIDENCE_SCHEMA,
            "environment": environment,
            "stateKey": state_key,
            "phase": phase,
            "controlPlaneCommit": request["controlPlaneCommit"],
            "observedAtUtc": "2026-10-08T23:55:00Z",
            "stateInventorySha256": request["state"]["managedAddressInventorySha256"],
            "facts": facts,
        }
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        return request, evidence

    @staticmethod
    def apply_facts(count):
        return {
            "binaryPlanSha256": "d" * 64,
            "planRecordSha256": "e" * 64,
            "planTextSha256": "a" * 64,
            "planJsonSha256": "b" * 64,
            "humanReviewed": True,
            "managedDeleteCount": count,
        }

    def verify(self, request, evidence):
        return PRIVATE.verify_private_bundle(
            REQUEST.canonical_bytes(request),
            REQUEST.canonical_bytes(evidence),
            expected_request_sha256=REQUEST.sha256(request),
            expected_evidence_sha256=REQUEST.sha256(evidence),
            now_utc=self.now,
        )

    def rejected(self, request, evidence):
        with self.assertRaises(PRIVATE.TeardownGateError):
            self.verify(request, evidence)

    def private_directory(self, request, evidence):
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
        directory.chmod(0o700)
        for name, value in (("request.json", request), ("evidence.json", evidence)):
            path = directory / name
            path.write_bytes(REQUEST.canonical_bytes(value))
            path.chmod(0o600)
        return temporary, directory

    def test_both_redacted_fixtures_are_accepted(self):
        for name in ("devWaveOnePlan", "testWaveTwoApply"):
            with self.subTest(name=name):
                item = self.fixture[name]
                result = self.verify(item["request"], item["evidence"])
                self.assertFalse(result["receipt"]["executionAuthorized"])

    def test_all_eight_phase_evidence_shapes_are_accepted(self):
        for phase in REQUEST.PHASES:
            with self.subTest(phase=phase):
                request, evidence = self.phase_bundle(phase)
                result = self.verify(request, evidence)
                self.assertEqual(result["receipt"]["phase"], phase)

    def test_receipt_digest_is_exact(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        result = self.verify(request, evidence)
        self.assertEqual(result["receiptSha256"], REQUEST.sha256(result["receipt"]))

    def test_receipt_is_redacted_and_non_authorizing(self):
        request, evidence = self.phase_bundle("safe-residue-delete")
        result = self.verify(request, evidence)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("sg-", serialized)
        self.assertNotIn("/home/", serialized)
        self.assertFalse(result["receipt"]["privatePathEmitted"])
        self.assertFalse(result["receipt"]["liveCommandExecuted"])

    def test_expected_request_digest_drift_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        with self.assertRaises(PRIVATE.TeardownGateError):
            PRIVATE.verify_private_bundle(REQUEST.canonical_bytes(request), REQUEST.canonical_bytes(evidence), expected_request_sha256="0" * 64, expected_evidence_sha256=REQUEST.sha256(evidence), now_utc=self.now)

    def test_expected_evidence_digest_drift_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        with self.assertRaises(PRIVATE.TeardownGateError):
            PRIVATE.verify_private_bundle(REQUEST.canonical_bytes(request), REQUEST.canonical_bytes(evidence), expected_request_sha256=REQUEST.sha256(request), expected_evidence_sha256="0" * 64, now_utc=self.now)

    def test_request_evidence_digest_binding_is_required(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        request["inputEvidenceSha256"] = "0" * 64
        self.rejected(request, evidence)

    def test_noncanonical_request_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        raw = json.dumps(request, indent=2).encode()
        with self.assertRaises(PRIVATE.TeardownGateError):
            PRIVATE.verify_private_bundle(raw, REQUEST.canonical_bytes(evidence), expected_request_sha256=REQUEST.sha256(request), expected_evidence_sha256=REQUEST.sha256(evidence), now_utc=self.now)

    def test_noncanonical_evidence_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        raw = json.dumps(evidence, indent=2).encode()
        with self.assertRaises(PRIVATE.TeardownGateError):
            PRIVATE.verify_private_bundle(REQUEST.canonical_bytes(request), raw, expected_request_sha256=REQUEST.sha256(request), expected_evidence_sha256=REQUEST.sha256(evidence), now_utc=self.now)

    def test_common_evidence_bindings_are_exact(self):
        for key, replacement in (
            ("environment", "aws-test"),
            ("stateKey", "environments/test/terraform.tfstate"),
            ("phase", "wave-two-plan"),
            ("controlPlaneCommit", "0" * 40),
            ("stateInventorySha256", "0" * 64),
        ):
            with self.subTest(key=key):
                request, evidence = self.phase_bundle("wave-one-plan")
                evidence[key] = replacement
                request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
                self.rejected(request, evidence)

    def test_stale_evidence_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        evidence["observedAtUtc"] = "2026-10-08T23:44:59Z"
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_future_evidence_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        evidence["observedAtUtc"] = "2026-10-09T00:00:01Z"
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_extra_phase_fact_is_rejected(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        evidence["facts"]["unexpected"] = False
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_controller_cleanup_requires_bound_target(self):
        request, evidence = self.phase_bundle("controller-cleanup")
        evidence["facts"]["reconciliationTargetBound"] = False
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_wave_one_counts_are_bound(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        evidence["facts"]["nonNetworkAddressCount"] = 1
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_apply_binary_plan_is_bound(self):
        request, evidence = self.phase_bundle("wave-two-apply")
        evidence["facts"]["binaryPlanSha256"] = "0" * 64
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_post_wave_one_requires_eks_absence(self):
        request, evidence = self.phase_bundle("post-wave-one-inventory")
        evidence["facts"]["eksAbsent"] = False
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_residue_identity_is_bound(self):
        request, evidence = self.phase_bundle("safe-residue-delete")
        evidence["facts"]["residueIdentitySha256"] = "0" * 64
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_already_attempted_residue_delete_is_rejected(self):
        request, evidence = self.phase_bundle("safe-residue-delete")
        evidence["facts"]["deletionAlreadyAttempted"] = True
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_wave_two_plan_requires_zero_dependencies(self):
        for key in ("safeResidueCount", "unknownDependencyCount", "controllerOwnedDependencyCount"):
            with self.subTest(key=key):
                request, evidence = self.phase_bundle("wave-two-plan")
                evidence["facts"][key] = 1
                request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
                self.rejected(request, evidence)

    def test_final_audit_requires_preserved_foundation(self):
        request, evidence = self.phase_bundle("final-read-only-audit")
        evidence["facts"]["protectedFoundationPreserved"] = False
        request["inputEvidenceSha256"] = REQUEST.sha256(evidence)
        self.rejected(request, evidence)

    def test_strict_private_bundle_reader_accepts_exact_scope(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            values = PRIVATE.StrictPrivateBundleReader(directory).read()
            self.assertEqual(set(values), {"request", "evidence"})
        finally:
            temporary.cleanup()

    def test_private_bundle_requires_absolute_path(self):
        with self.assertRaises(PRIVATE.TeardownGateError):
            PRIVATE.StrictPrivateBundleReader(Path("relative"))

    def test_private_bundle_rejects_directory_mode_drift(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            directory.chmod(0o755)
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                PRIVATE.StrictPrivateBundleReader(directory).read()
        finally:
            temporary.cleanup()

    def test_private_bundle_rejects_file_mode_drift(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            (directory / "request.json").chmod(0o644)
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                PRIVATE.StrictPrivateBundleReader(directory).read()
        finally:
            temporary.cleanup()

    def test_private_bundle_rejects_extra_entry(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            extra = directory / "extra.json"
            extra.write_bytes(b"{}\n")
            extra.chmod(0o600)
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                PRIVATE.StrictPrivateBundleReader(directory).read()
        finally:
            temporary.cleanup()

    def test_private_bundle_rejects_hard_link(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        outside = Path(temporary.name).parent / f"{Path(temporary.name).name}-hardlink"
        try:
            os.link(directory / "request.json", outside)
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                PRIVATE.StrictPrivateBundleReader(directory).read()
        finally:
            if outside.exists():
                outside.unlink()
            temporary.cleanup()

    def test_private_bundle_rejects_symlink(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        target = directory.parent / f"{directory.name}-symlink-target"
        try:
            target.write_bytes((directory / "request.json").read_bytes())
            target.chmod(0o600)
            (directory / "request.json").unlink()
            (directory / "request.json").symlink_to(target)
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                PRIVATE.StrictPrivateBundleReader(directory).read()
        finally:
            if target.exists():
                target.unlink()
            temporary.cleanup()

    def test_cli_binds_commit_environment_and_phase(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            args = self.cli_args(directory, request, evidence)
            result = CLI.run(args, now_utc=self.now)
            self.assertEqual(result["receipt"]["phase"], "wave-one-plan")
            args[args.index("aws-dev")] = "aws-test"
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                CLI.run(args, now_utc=self.now)
        finally:
            temporary.cleanup()

    def test_cli_confirmation_is_exact(self):
        request, evidence = self.phase_bundle("wave-one-plan")
        temporary, directory = self.private_directory(request, evidence)
        try:
            args = self.cli_args(directory, request, evidence)
            args[-1] = "approve-everything"
            with self.assertRaises(PRIVATE.PrivatePreflightStopped):
                CLI.run(args, now_utc=self.now)
        finally:
            temporary.cleanup()

    def test_system_clock_is_single_read(self):
        clock = PRIVATE.SystemUtcClock()
        self.assertTrue(clock.now().endswith("Z"))
        with self.assertRaises(PRIVATE.TeardownGateError):
            clock.now()

    @staticmethod
    def cli_args(directory, request, evidence):
        return [
            "verify",
            "--bundle-directory", str(directory),
            "--expected-control-plane-commit", request["controlPlaneCommit"],
            "--environment", request["environment"],
            "--phase", request["phase"],
            "--expected-request-sha256", REQUEST.sha256(request),
            "--expected-evidence-sha256", REQUEST.sha256(evidence),
            "--confirm", CLI.CONFIRMATION,
        ]


if __name__ == "__main__":
    unittest.main()
