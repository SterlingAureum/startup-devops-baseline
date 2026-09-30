#!/usr/bin/env python3
"""Offline tests for the guarded aws-dev post-create qualification."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_post_create_qualification_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"
MAIN = "1" * 40


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": MAIN,
        "expectedAwsAccountId": ACCOUNT,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "privateSemanticRecoveryRequestPath": "/private/recovery-request.json",
        "privateSemanticRecoveryEvidencePath": "/private/recovery-evidence.json",
        "privateSemanticRecoveryResultPath": "/private/recovery-result.json",
        "privateQualificationOutputDirectory": "/private/qualification-output",
        "recoveryBoundary": {
            "recoveryControlPlaneCommit": EXECUTOR.RECOVERY_CONTROL_PLANE_COMMIT,
            "privateRecoveryRequestSha256": EXECUTOR.RECOVERY_REQUEST_SHA256,
            "privateRecoveryEvidenceSha256": EXECUTOR.RECOVERY_EVIDENCE_SHA256,
            "privateRecoveryResultSha256": EXECUTOR.RECOVERY_RESULT_SHA256,
            "liveStateSha256": EXECUTOR.LIVE_STATE_SHA256,
            "stateAddressInventorySha256": EXECUTOR.STATE_INVENTORY_SHA256,
            "normalizedCheckResultsSha256": EXECUTOR.NORMALIZED_CHECK_RESULTS_SHA256,
            "stateSerial": 9,
            "managedStateAddressCount": 90,
            "reviewedDataStateAddressCount": 6,
            "priorStateDataAddressCount": 7,
            "totalStateAddressCount": 103,
            "checkResultCount": 28,
            "checkPassStatusCount": 56,
            "semanticStateEqual": True,
            "unexplainedAddressCount": 0,
            "environmentCreated": True,
        },
        "approval": {"notBeforeUtc": "2026-10-01T00:00:00Z", "expiresAtUtc": "2026-10-01T01:00:00Z"},
        "executionBoundary": {
            "awsIdentityRead": True,
            "eksClusterRead": True,
            "eksNodegroupRead": True,
            "eksAddonRead": True,
            "privateKubeconfigWrite": True,
            "kubernetesApiRead": True,
            "terraformCommand": False,
            "stateMutation": False,
            "awsMutation": False,
            "kubernetesPersistentMutation": False,
            "argocdOperation": False,
            "helmOperation": False,
            "externalSecretsPreflight": False,
            "secretValueRead": False,
            "automaticRetry": False,
            "automaticRollback": False,
            "automaticTeardown": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_mutation_authority_is_rejected(self):
        candidate = request()
        candidate["executionBoundary"]["awsMutation"] = True
        with self.assertRaisesRegex(EXECUTOR.QualificationError, "Execution boundary"):
            EXECUTOR.validate_request(candidate)

    def test_recovery_boundary_cannot_be_relaxed(self):
        candidate = request()
        candidate["recoveryBoundary"]["semanticStateEqual"] = False
        with self.assertRaisesRegex(EXECUTOR.QualificationError, "Recovery boundary"):
            EXECUTOR.validate_request(candidate)

    def test_verification_is_command_free(self):
        context = {"request": request(), "request_path": Path("/private/request.json"), "remaining": 2400}
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_command_authorized"])
        self.assertFalse(result["gitops_bootstrap_authorized"])
        self.assertFalse(result["external_secrets_preflight_authorized"])


class RecoveryEvidenceTests(unittest.TestCase):
    def test_exact_recovery_result_is_accepted(self):
        value = {
            "schemaVersion": "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-result-v1",
            "status": "aws-dev-saved-plan-apply-semantically-validated",
            "control_plane_commit": EXECUTOR.RECOVERY_CONTROL_PLANE_COMMIT,
            "private_recovery_request_sha256": EXECUTOR.RECOVERY_REQUEST_SHA256,
            "recovery_evidence_sha256": EXECUTOR.RECOVERY_EVIDENCE_SHA256,
            "live_state_sha256": EXECUTOR.LIVE_STATE_SHA256,
            "state_address_inventory_sha256": EXECUTOR.STATE_INVENTORY_SHA256,
            "normalized_check_results_sha256": EXECUTOR.NORMALIZED_CHECK_RESULTS_SHA256,
            "state_serial": 9,
            "managed_state_address_count": 90,
            "reviewed_data_state_address_count": 6,
            "prior_state_data_address_count": 7,
            "total_state_address_count": 103,
            "check_result_count": 28,
            "check_pass_status_count": 56,
            "semantic_state_equal": True,
            "unexplained_address_count": 0,
            "eks_cluster_active": True,
            "environment_created": True,
            "state_push_executed": False,
            "terraform_apply_executed_by_recovery": False,
            "terraform_init_executed": False,
            "terraform_plan_executed": False,
            "automatic_retry_performed": False,
            "automatic_rollback_performed": False,
        }
        EXECUTOR.validate_recovery_result(value)
        value["semantic_state_equal"] = False
        with self.assertRaisesRegex(EXECUTOR.QualificationError, "semantic_state_equal"):
            EXECUTOR.validate_recovery_result(value)


class LiveShapeTests(unittest.TestCase):
    def nodes(self) -> dict:
        return {"items": [{
            "metadata": {"labels": {
                "workload": "system",
                "eks.amazonaws.com/nodegroup": EXECUTOR.NODEGROUP_NAME,
            }},
            "spec": {},
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "nodeInfo": {"kubeletVersion": "v1.36.3-eks-fixture"},
            },
        } for _ in range(EXECUTOR.EXPECTED_NODE_COUNT)]}

    def test_exact_ready_node_inventory_is_accepted(self):
        EXECUTOR.require_nodes(self.nodes())

    def test_non_ready_node_is_rejected(self):
        value = self.nodes()
        value["items"][0]["status"]["conditions"][0]["status"] = "False"
        with self.assertRaisesRegex(EXECUTOR.QualificationError, "not Ready"):
            EXECUTOR.require_nodes(value)

    def test_nodegroup_scaling_drift_is_rejected(self):
        value = {"nodegroup": {
            "clusterName": EXECUTOR.CLUSTER_NAME,
            "nodegroupName": EXECUTOR.NODEGROUP_NAME,
            "status": "ACTIVE",
            "version": EXECUTOR.KUBERNETES_MINOR,
            "capacityType": "ON_DEMAND",
            "instanceTypes": ["t3.medium"],
            "labels": {"workload": "system"},
            "scalingConfig": {"minSize": 2, "maxSize": 4, "desiredSize": 2},
            "health": {"issues": []},
        }}
        with self.assertRaisesRegex(EXECUTOR.QualificationError, "scaling changed"):
            EXECUTOR.require_nodegroup(value)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.output = self.private / "qualification-output"
        self.request_path = self.private / "request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)
        value = request()
        value["privateQualificationOutputDirectory"] = str(self.output)
        self.context = {"request": value, "request_path": self.request_path, "output": self.output, "remaining": 2400}
        self.commands: list[list[str]] = []
        self.cluster_arn = f"arn:aws:eks:{EXECUTOR.AWS_REGION}:{ACCOUNT}:cluster/{EXECUTOR.CLUSTER_NAME}"
        self.endpoint = "https://private-fixture.eks.amazonaws.com"

    def tearDown(self):
        self.temp.cleanup()

    def completed(self, arguments, value=b""):
        if not isinstance(value, bytes):
            value = json.dumps(value).encode()
        return subprocess.CompletedProcess(arguments, 0, value, b"")

    def runner(self, arguments, environment, _timeout, _cwd):
        self.commands.append(arguments)
        joined = " ".join(arguments)
        if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
            return self.completed(arguments, {"Account": ACCOUNT})
        if arguments[:3] == ["aws", "eks", "describe-cluster"]:
            return self.completed(arguments, {"cluster": {
                "name": EXECUTOR.CLUSTER_NAME,
                "arn": self.cluster_arn,
                "status": "ACTIVE",
                "version": EXECUTOR.KUBERNETES_MINOR,
                "endpoint": self.endpoint,
                "resourcesVpcConfig": {"endpointPublicAccess": True, "endpointPrivateAccess": True},
                "logging": {"clusterLogging": [{"types": ["api"], "enabled": False}]},
            }})
        if arguments[:3] == ["aws", "eks", "list-nodegroups"]:
            return self.completed(arguments, {"nodegroups": [EXECUTOR.NODEGROUP_NAME]})
        if arguments[:3] == ["aws", "eks", "describe-nodegroup"]:
            return self.completed(arguments, {"nodegroup": {
                "clusterName": EXECUTOR.CLUSTER_NAME,
                "nodegroupName": EXECUTOR.NODEGROUP_NAME,
                "status": "ACTIVE",
                "version": EXECUTOR.KUBERNETES_MINOR,
                "capacityType": "ON_DEMAND",
                "instanceTypes": ["t3.medium"],
                "labels": {"workload": "system"},
                "scalingConfig": {"minSize": 4, "maxSize": 4, "desiredSize": 4},
                "health": {"issues": []},
            }})
        if arguments[:3] == ["aws", "eks", "list-addons"]:
            return self.completed(arguments, {"addons": sorted(EXECUTOR.EXPECTED_ADDONS)})
        if arguments[:3] == ["aws", "eks", "describe-addon"]:
            addon = arguments[arguments.index("--addon-name") + 1]
            return self.completed(arguments, {"addon": {"addonName": addon, "status": "ACTIVE", "health": {"issues": []}}})
        if arguments[:3] == ["aws", "eks", "update-kubeconfig"]:
            path = Path(environment["KUBECONFIG"])
            path.write_text("fixture-private-kubeconfig\n")
            path.chmod(0o600)
            return self.completed(arguments, b"updated\n")
        if "config current-context" in joined:
            return self.completed(arguments, (self.cluster_arn + "\n").encode())
        if "config view --minify -o json" in joined:
            return self.completed(arguments, {"clusters": [{"cluster": {"server": self.endpoint}}]})
        if "get --raw=/readyz" in joined:
            return self.completed(arguments, b"ok\n")
        if "get nodes -o json" in joined:
            nodes = []
            for index in range(EXECUTOR.EXPECTED_NODE_COUNT):
                nodes.append({
                    "metadata": {"name": f"node-{index}", "labels": {"workload": "system", "eks.amazonaws.com/nodegroup": EXECUTOR.NODEGROUP_NAME}},
                    "spec": {},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}], "nodeInfo": {"kubeletVersion": "v1.36.3-eks-fixture"}},
                })
            return self.completed(arguments, {"items": nodes})
        if "get namespace argocd" in joined:
            return self.completed(arguments, b"")
        raise AssertionError(arguments)

    def test_execute_qualifies_without_mutation(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"PATH": os.environ.get("PATH", ""), "CONFIRM_AWS_DEV_POST_CREATE_QUALIFICATION": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 10, 1, 0, 20, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-post-create-qualified-for-gitops-bootstrap")
        self.assertEqual(result["ready_node_count"], 4)
        self.assertTrue(result["argocd_namespace_absent"])
        self.assertFalse(result["gitops_bootstrap_executed"])
        self.assertFalse(result["external_secrets_preflight_executed"])
        self.assertFalse(any(command[0] in {"terraform", "helm", "argocd"} for command in self.commands))
        self.assertFalse(any(token in {"apply", "delete", "patch"} for command in self.commands for token in command))

    def test_successor_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {
                "CONFIRM_AWS_DEV_POST_CREATE_QUALIFICATION": EXECUTOR.CONFIRMATION,
                "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP": "unsafe",
            }, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.QualificationError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
