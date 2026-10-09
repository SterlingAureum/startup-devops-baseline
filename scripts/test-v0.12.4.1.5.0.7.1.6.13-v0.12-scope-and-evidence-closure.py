#!/usr/bin/env python3
"""Offline mutation tests for the final v0.12 scope closure."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.13-v0.12-scope-and-evidence-closure"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = load(ROOT / f"scripts/check-{PREFIX}.py", "v012_scope_closure_check_under_test")
CONTRACT = json.loads((ROOT / f"delivery/contracts/{PREFIX}.json").read_text())
MANIFEST = json.loads((ROOT / "delivery/contracts/v0.12-final-evidence-manifest.json").read_text())
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())


class V012ScopeClosureTests(unittest.TestCase):
    def reject_contract(self, mutation):
        value = deepcopy(CONTRACT)
        mutation(value)
        with self.assertRaises(CHECK.ContractError):
            CHECK.validate_contract(value, FIXTURE)

    def reject_manifest(self, mutation):
        value = deepcopy(MANIFEST)
        mutation(value)
        with self.assertRaises(CHECK.ContractError):
            CHECK.validate_manifest(value, FIXTURE)

    def test_exact_repository_closure_is_valid(self):
        result = CHECK.validate_repository(ROOT)
        self.assertEqual(result["sourceEvidenceCount"], 8)
        self.assertEqual(result["forbiddenClaimCount"], 8)
        self.assertEqual(result["deferredWorkCount"], 10)
        self.assertTrue(result["v012ScopeClosed"])
        self.assertFalse(result["productionReadinessClaimed"])
        self.assertFalse(result["newLiveExecutionAuthorized"])

    def test_baseline_manifest_and_source_inventory_are_immutable(self):
        self.reject_contract(lambda value: value.update(implementationBaselineCommit="0" * 40))
        self.reject_contract(lambda value: value.update(manifestSha256="0" * 64))
        self.reject_manifest(lambda value: value["sourceEvidence"].pop())
        self.reject_manifest(lambda value: value["sourceEvidence"][0].update(path="replacement.json"))

    def test_production_readiness_and_live_authority_cannot_be_claimed(self):
        self.reject_manifest(lambda value: value.update(productionReadinessClaimed=True))
        self.reject_manifest(lambda value: value.update(newLiveExecutionAuthorized=True))
        self.reject_contract(lambda value: value["closureAssertions"].update(productionReadinessClaimed=True))
        self.reject_contract(lambda value: value["packageProducer"].update(liveAdapterAdded=True))

    def test_aws_test_and_prod_cannot_be_overclaimed(self):
        self.reject_manifest(lambda value: CHECK.by_environment(value)["aws-test"].update(freshIntegratedLiveLifecycleExecutedInV012=True))
        self.reject_manifest(lambda value: CHECK.by_environment(value)["aws-prod"].update(acceptance="qualified"))
        self.reject_contract(lambda value: value["closureAssertions"].update(awsProdLiveQualified=True))

    def test_upgrade_and_live_teardown_remain_deferred(self):
        self.reject_contract(lambda value: value["closureAssertions"].update(externalSecretsLiveUpgradeExecuted=True))
        self.reject_contract(lambda value: value["closureAssertions"].update(sharedLiveTeardownAdaptersImplemented=True))
        self.reject_manifest(lambda value: value["forbiddenClaims"].remove("external-secrets-live-upgrade-passed"))
        self.reject_manifest(lambda value: value["forbiddenClaims"].remove("shared-dev-test-teardown-has-live-command-adapters"))

    def test_remote_state_backend_remains_separate_and_retained(self):
        self.reject_manifest(lambda value: value["stateBackend"].update(applicationTeardownIncludesBackend=True))
        self.reject_manifest(lambda value: value["stateBackend"].update(backendRetired=True))
        self.reject_manifest(lambda value: value["stateBackend"].update(zeroOngoingBackendCostClaimed=True))
        self.reject_contract(lambda value: value["closureAssertions"].update(remoteStateBackendRetired=True))

    def test_review_and_commercial_rehearsal_deferrals_cannot_disappear(self):
        self.reject_manifest(lambda value: value["deferredWork"].pop("repositoryAndArchitectureReview"))
        self.reject_manifest(lambda value: value["deferredWork"].pop("auditMaterialPhysicalSeparation"))
        self.reject_manifest(lambda value: value["deferredWork"].pop("freshIntegratedDevTestProdRehearsal"))
        self.reject_manifest(lambda value: value["deferredWork"].pop("originalV0125BroaderDrAndMeasuredRtoRpo"))
        self.reject_manifest(lambda value: value["deferredWork"].pop("originalV0126ProductionControls"))
        self.reject_manifest(lambda value: value["deferredWork"].pop("originalV0127RepositoryWideTechnicalMatrix"))
        self.reject_contract(lambda value: value["closureAssertions"].update(repositoryWideHumanReviewComplete=True))

    def test_public_closure_records_are_redacted(self):
        raw = json.dumps({"contract": CONTRACT, "manifest": MANIFEST, "fixture": FIXTURE}, sort_keys=True).lower()
        for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
            self.assertNotIn(marker, raw)


if __name__ == "__main__":
    unittest.main()
