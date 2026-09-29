#!/usr/bin/env python3
"""Offline tests for the External Secrets 2.9.0 live-preflight executor."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5-external-secrets-live-preflight.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("external_secrets_live_preflight_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5-external-secrets-live-preflight-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "expectedKubernetesMinor": EXECUTOR.KUBERNETES_MINOR,
        "privateChartPath": "/private/external-secrets-2.9.0.tgz",
        "privateChartSha256": EXECUTOR.CANDIDATE_CHART_SHA256,
        "privateRenderPath": "/private/external-secrets-2.9.0.render.yaml",
        "privateRenderSha256": EXECUTOR.CANDIDATE_RENDER_SHA256,
        "privateOutputDirectory": "/private/preflight-output",
        "approval": {
            "notBeforeUtc": "2026-09-29T03:00:00Z",
            "expiresAtUtc": "2026-09-29T04:00:00Z",
        },
        "executionBoundary": {
            "awsReadOnly": True,
            "kubernetesReadOnly": True,
            "kubernetesServerSideDryRun": True,
            "kubernetesPersistentMutation": False,
            "gitMutation": False,
            "argocdOperation": False,
            "helmOperation": False,
            "secretValueRead": False,
            "automaticRetry": False,
            "automaticRollback": False,
        },
    }


def application(name: str, expected_main: str = "1" * 40) -> dict:
    if name == "external-secrets":
        source = {
            "repoURL": "https://charts.external-secrets.io",
            "chart": "external-secrets",
            "targetRevision": "2.8.0",
        }
        revision = "2.8.0"
    else:
        source = {
            "repoURL": "https://github.com/SterlingAureum/startup-devops-baseline.git",
            "targetRevision": "main",
            "path": "clusters/aws/overlays/dev/security/external-secrets/startup-apps",
        }
        revision = expected_main
    return {
        "metadata": {"name": name, "namespace": "argocd"},
        "spec": {
            "source": source,
            "syncPolicy": {"automated": {"prune": True, "selfHeal": True}},
        },
        "status": {
            "sync": {"status": "Synced", "revision": revision},
            "health": {"status": "Healthy"},
        },
    }


def deployment(name: str) -> dict:
    generation = 4
    return {
        "metadata": {"name": name, "namespace": "external-secrets", "generation": generation},
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "serviceAccountName": name,
                    "containers": [{"name": "controller", "image": EXECUTOR.EXPECTED_IMAGE}],
                }
            },
        },
        "status": {
            "observedGeneration": generation,
            "readyReplicas": 1,
            "updatedReplicas": 1,
            "availableReplicas": 1,
        },
    }


def ready() -> dict:
    return {"conditions": [{"type": "Ready", "status": "True"}]}


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_persistent_mutation_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["kubernetesPersistentMutation"] = True
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "Execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_candidate_digest_change_is_rejected(self):
        value = request()
        value["privateRenderSha256"] = "0" * 64
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "render digest"):
            EXECUTOR.validate_request(value)

    def test_window_longer_than_one_hour_is_rejected(self):
        value = request()
        value["approval"]["expiresAtUtc"] = "2026-09-29T04:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "at most one hour"):
            EXECUTOR.validate_request(value)

    def test_verification_result_is_command_free_and_unauthorized(self):
        context = {
            "request": request(),
            "request_path": Path("/private/request.json"),
            "remaining": 1800,
        }
        with patch.object(EXECUTOR, "file_sha256", return_value="2" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["preflight_execution_authorized"])
        self.assertFalse(result["git_pin_mutation_authorized"])
        self.assertFalse(result["secret_value_read_authorized"])


class LiveShapeTests(unittest.TestCase):
    def test_exact_applications_are_accepted(self):
        expected_main = "1" * 40
        operator = EXECUTOR.validate_application(application("external-secrets"), "external-secrets", expected_main)
        resources = EXECUTOR.validate_application(application("external-secrets-startup-apps"), "external-secrets-startup-apps", expected_main)
        self.assertEqual(operator["syncStatus"], "Synced")
        self.assertEqual(resources["syncRevision"], expected_main)

    def test_active_application_operation_is_rejected(self):
        value = application("external-secrets")
        value["operation"] = {"sync": {}}
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "active operation"):
            EXECUTOR.validate_application(value, "external-secrets", "1" * 40)

    def test_exact_three_deployments_are_accepted(self):
        value = {"items": [deployment(name) for name in sorted(EXECUTOR.EXPECTED_DEPLOYMENTS)]}
        projection = EXECUTOR.validate_deployments(value)
        self.assertEqual(len(projection), 3)

    def test_candidate_image_before_upgrade_is_rejected(self):
        value = {"items": [deployment(name) for name in sorted(EXECUTOR.EXPECTED_DEPLOYMENTS)]}
        value["items"][0]["spec"]["template"]["spec"]["containers"][0]["image"] = "ghcr.io/external-secrets/external-secrets:v2.9.0"
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "image changed"):
            EXECUTOR.validate_deployments(value)

    def test_exact_rbac_counts_are_accepted(self):
        items = []
        for kind, count in EXECUTOR.EXPECTED_RBAC_COUNTS.items():
            for index in range(count):
                items.append({"kind": kind, "metadata": {"name": f"item-{kind}-{index}", "namespace": "external-secrets"}})
        self.assertEqual(len(EXECUTOR.validate_rbac({"items": items})), 8)

    def test_repository_crds_must_serve_and_store_v1(self):
        value = {"items": [
            {"metadata": {"name": name}, "spec": {"versions": [{"name": "v1", "served": True, "storage": True}]}}
            for name in ("externalsecrets.external-secrets.io", "secretstores.external-secrets.io")
        ]}
        self.assertEqual(len(EXECUTOR.validate_crds(value)), 2)
        value["items"][0]["spec"]["versions"][0]["storage"] = False
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "serve and store v1"):
            EXECUTOR.validate_crds(value)

    def test_external_secret_awscurrent_is_accepted_without_secret_data(self):
        value = {
            "metadata": {"name": "demo-api-postgresql", "namespace": "startup-apps"},
            "spec": {
                "secretStoreRef": {"name": "aws-secrets-manager", "kind": "SecretStore"},
                "data": [{
                    "secretKey": "DATABASE_URL",
                    "remoteRef": {
                        "key": "startup-devops-baseline-dev/demo-api/postgresql",
                        "property": "DATABASE_URL",
                        "version": "AWSCURRENT",
                        "conversionStrategy": "Default",
                        "decodingStrategy": "None",
                        "metadataPolicy": "None",
                    },
                }],
            },
            "status": ready(),
        }
        projection = EXECUTOR.validate_external_secret(value)
        self.assertTrue(projection["ready"])
        self.assertNotIn("data", value.get("status", {}))

    def test_force_sync_annotation_is_rejected(self):
        value = {
            "metadata": {"name": "demo-api-postgresql", "namespace": "startup-apps", "annotations": {"force-sync": "1"}},
            "spec": {},
            "status": ready(),
        }
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "force-sync"):
            EXECUTOR.validate_external_secret(value)


class CommandBoundaryTests(unittest.TestCase):
    def test_read_inventory_never_gets_kubernetes_secret(self):
        commands = [command for _, command in EXECUTOR.snapshot_commands()]
        flattened = [token for command in commands for token in command]
        self.assertNotIn("secret", flattened)
        self.assertNotIn("secrets", flattened)
        self.assertNotIn("get-secret-value", flattened)
        self.assertTrue(all(command[0] == "kubectl" and "get" in command for command in commands))

    def test_exact_server_dry_run_identity_inventory_is_accepted(self):
        value = "\n".join(f"configmap/item-{index}" for index in range(EXECUTOR.EXPECTED_RENDER_OBJECT_COUNT)).encode() + b"\n"
        self.assertEqual(len(EXECUTOR.validate_dry_run_stdout(value)), EXECUTOR.EXPECTED_RENDER_OBJECT_COUNT)

    def test_non_identity_dry_run_output_is_rejected(self):
        lines = [f"configmap/item-{index}" for index in range(EXECUTOR.EXPECTED_RENDER_OBJECT_COUNT - 1)]
        lines.append("warning: changed")
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "non-identity"):
            EXECUTOR.validate_dry_run_stdout(("\n".join(lines) + "\n").encode())

    def test_command_failure_is_private_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def runner(arguments, environment, timeout, cwd):
                return subprocess.CompletedProcess(arguments, 1, stdout=b"private-out", stderr=b"private-error")

            with self.assertRaisesRegex(EXECUTOR.CommandFailure, "read failed"):
                EXECUTOR.run_logged(output, "read", ["kubectl", "get", "x"], {}, runner, ROOT)
            self.assertEqual(stat.S_IMODE((output / "read.stdout").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((output / "read.stderr").stat().st_mode), 0o600)

    def test_child_environment_strips_all_confirmation_variables(self):
        with patch.dict(os.environ, {"CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT": EXECUTOR.CONFIRMATION, "CONFIRM_TERRAFORM_APPLY": "yes"}, clear=False):
            environment = EXECUTOR.safe_environment()
        self.assertFalse(any(key.startswith("CONFIRM_") for key in environment))
        self.assertEqual(environment["AWS_REGION"], EXECUTOR.AWS_REGION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
