#!/usr/bin/env python3
"""Offline regressions: no credentials, AWS, Kubernetes or Terraform required."""
import argparse
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("recovery", Path(__file__).with_name(
    "check-v0.11.9.3.6.7.5-aws-test-recovery-root-plan.py"))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.contract = m.load(m.ROOT / m.CONTRACT)
        self.now = m.utc("2026-09-13T01:00:00Z")
        self.obs = {"status": "aws-test-recovery-root-preflight-complete",
                    "observed_at_utc": "2026-09-13T00:59:00Z",
                    "control_plane_commit": "a" * 40}
        self.plan = {
            "target_environment": "aws-test", "control_plane_commit": "a" * 40,
            "candidate_release_id": m.RELEASE, "historical_spend_usd": None,
            "historical_spend_unattributed": True, "additional_budget_limit_usd": "8.00",
            "start_utc": "2026-09-13T01:10:00Z",
            "cleanup_complete_by_utc": "2026-09-13T04:10:00Z",
            "cleanup_reserve_seconds": 3600,
            "hourly_upper_bound_usd": {k: "0.10" for k in m.COMPONENTS},
            "fixed_and_uncertainty_reserve_usd": "1.00",
            "estimate_covers_idle_and_post_root_peak": True,
            "estimate_covers_all_resources_not_only_tag_matches": True,
            "pricing_reference": "OFFLINE FIXTURE ONLY - not a pricing estimate",
            "reviewed_scope": {k: True for k in m.SCOPES},
            **{k: False for k in ("root_deployment_authorized", "credential_transfer_authorized",
                "dns_write_authorized", "teardown_authorized", "automatic_budget_enforcement")},
        }

    def check(self):
        return m.check_plan(self.plan, self.obs, self.contract, self.now)

    def test_plan_passes_without_authorizing(self):
        self.assertFalse(self.check()["root_deployment_authorized"])

    def test_budget_includes_elapsed_idle_time(self):
        self.plan["hourly_upper_bound_usd"] = {k: "0" for k in m.COMPONENTS}
        self.plan["hourly_upper_bound_usd"]["eks"] = "1.80"
        self.plan["start_utc"] = "2026-09-13T06:00:00Z"
        self.plan["cleanup_complete_by_utc"] = "2026-09-13T08:00:00Z"
        with self.assertRaisesRegex(ValueError, "elapsed-time"):
            self.check()

    def test_eight_hour_limit(self):
        self.plan["cleanup_complete_by_utc"] = "2026-09-13T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "eight-hour"):
            self.check()

    def test_beyond_available_day(self):
        self.plan["cleanup_complete_by_utc"] = "2026-09-14T01:00:00Z"
        with self.assertRaisesRegex(ValueError, "window-boundary"):
            self.check()

    def test_expired_future_observations(self):
        for value in ("2026-09-13T00:00:00Z", "2026-09-13T02:00:00Z"):
            with self.subTest(value=value):
                self.obs["observed_at_utc"] = value
                with self.assertRaises(ValueError):
                    self.check()

    def test_missing_cost_scope_and_guessed_history(self):
        for key, value in (("historical_spend_usd", "0"),
                           ("additional_budget_limit_usd", "12"),
                           ("estimate_covers_all_resources_not_only_tag_matches", False),
                           ("cleanup_reserve_seconds", 0), ("pricing_reference", ""),
                           ("control_plane_commit", "b" * 40), ("target_environment", "aws-dev")):
            with self.subTest(key=key):
                old = self.plan[key]
                self.plan[key] = value
                with self.assertRaises(ValueError):
                    self.check()
                self.plan[key] = old

    def test_nonfinite_numeric_and_negative_costs(self):
        for value in ("NaN", "Infinity", "-1", 1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.amount(value)

    def test_cascade_review_and_mutation_flags(self):
        for key in m.SCOPES:
            self.plan["reviewed_scope"][key] = False
            with self.assertRaises(ValueError):
                self.check()
            self.plan["reviewed_scope"][key] = True
        self.plan["credential_transfer_authorized"] = True
        with self.assertRaises(ValueError):
            self.check()


class InputTests(unittest.TestCase):
    def test_explicit_context_blocks_other_exec_plugins(self):
        c = {"clusters": [{"cluster": {"server": "https://fixture.invalid"}}],
             "users": [{"user": {"exec": {"command": "sh", "args": []}}}]}
        with self.assertRaisesRegex(ValueError, "exec-plugin"):
            m.kube_auth(c, "https://fixture.invalid")

    def test_zero_replicas_and_stale_generation(self):
        for obj in ({"spec": {"replicas": 0}}, {"spec": {"replicas": 1},
             "metadata": {"generation": 2}, "status": {"readyReplicas": 1, "observedGeneration": 1}}):
            with self.assertRaises(ValueError):
                m.ready(obj)

    def test_private_symlinks_and_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "input"
            p.write_text("{}")
            p.chmod(0o644)
            with self.assertRaises(ValueError):
                m.private(p)
            p.chmod(0o600)
            self.assertEqual(m.private(p), p)
            link = Path(folder) / "link"
            link.symlink_to(p)
            with self.assertRaises(ValueError):
                m.private(link)

    def test_no_temporary_or_repo_evidence(self):
        for path in (Path("/tmp/test.json"), Path("/var/tmp/test.json"), m.ROOT / "out"):
            with self.assertRaises(ValueError):
                m.persistent(path)

    def test_duplicate_input_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "input"
            p.write_text('{"a": 1, "a": 2}')
            with self.assertRaises(ValueError):
                m.load(p)

    def test_remote_main_drift(self):
        def git(args):
            if args == ["branch", "--show-current"]: return "main"
            if args[0] == "rev-parse": return "a" * 40
            if args[0] == "ls-remote": return "b" * 40 + "\trefs/heads/main"
            return ""
        with self.assertRaisesRegex(ValueError, "remote-main"):
            m.exact_main("a" * 40, "c" * 40, git)


class ObservationTests(unittest.TestCase):
    def run_observation(self, wrong_account=False, extra_root=False, denied=False):
        contract = m.load(m.ROOT / m.CONTRACT)
        inputs = {"aws_account_id": "0" * 12, "management_cidr": "192.0.2.1/32",
                  "kubeconfig_path": "/fixture/config"}
        outputs = {k: {"value": v} for k, v in {
            "vpc_id": "fixture-vpc", "external_secrets_secret_arn": "fixture-container",
            "aws_load_balancer_controller_role_arn": "fixture-alb-role",
            "karpenter_controller_role_arn": "fixture-karpenter-role"}.items()}
        calls = []
        def run(args, stdout, stderr, **kwargs):
            calls.append(args)
            label = Path(stdout.name).stem
            require_verbs = ("get", "config") if args[0] == "kubectl" else (
                "get-caller-identity", "list-clusters", "describe-cluster",
                "describe-secret", "describe-instances", "describe-volumes")
            self.assertTrue(any(v in args for v in require_verbs))
            if denied:
                stderr.write(b"PRIVATE ERROR")
                return subprocess.CompletedProcess(args, 1)
            obj = {}
            if label == "identity": obj = {"Account": "wrong" if wrong_account else "0" * 12}
            elif label == "cluster-inventory": obj = {"clusters": [m.CLUSTER]}
            elif label == "cluster": obj = {"cluster": {"status": "ACTIVE",
                "endpoint": "https://fixture.invalid", "resourcesVpcConfig": {
                "endpointPublicAccess": True, "endpointPrivateAccess": True,
                "publicAccessCidrs": [inputs["management_cidr"]], "vpcId": "fixture-vpc"}}}
            elif label == "metadata-observation": obj = {"ARN": "fixture-container"}
            elif label == "kubeconfig": obj = {
                "clusters": [{"cluster": {"server": "https://fixture.invalid"}}],
                "users": [{"user": {"exec": {"command": "aws", "args": ["--region",
                "us-east-1", "eks", "get-token", "--cluster-name", m.CLUSTER, "--output", "json"]}}}]}
            elif label == "readyz":
                stdout.write(b"ok")
                return subprocess.CompletedProcess(args, 0)
            elif label.endswith("-irsa"):
                role = "fixture-alb-role" if label.startswith(m.ALB) else "fixture-karpenter-role"
                obj = {"metadata": {"annotations": {"eks.amazonaws.com/role-arn": role}}}
            elif label == "applications":
                alb = {"metadata": {"name": m.ALB}, "status": {
                    "sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
                    "spec": {"source": {"chart": m.ALB, "targetRevision": "1.14.0",
                        "helm": {"valuesObject": {"vpcId": "fixture-vpc",
                        "clusterName": m.CLUSTER, "region": "us-east-1"}}}}}
                obj = {"items": [alb] + ([{"metadata": {"name": m.APP}}] if extra_root else [])}
            elif label == "compute-inventory": obj = {"Reservations": []}
            elif label == "volume-inventory": obj = {"Volumes": []}
            else: obj = {"metadata": {"generation": 1}, "spec": {"replicas": 1,
                "template": {"spec": {"containers": [{"image": "quay.io/argoproj/argocd:v3.5.2"}]}}},
                "status": {"readyReplicas": 1, "observedGeneration": 1}}
            stdout.write(json.dumps(obj).encode())
            return subprocess.CompletedProcess(args, 0)
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o700)
            args = argparse.Namespace(output_directory=Path(folder) / "out", inputs=Path(folder) / "input",
                                      expected_main="a" * 40)
            args.inputs.write_text("{}")
            with patch.object(m, "local_inputs", return_value=(contract, inputs, {"outputs": outputs})), \
                 patch.object(m, "persistent"), patch.object(m.subprocess, "run", side_effect=run), \
                 patch.dict(os.environ, {}, clear=True):
                if wrong_account or extra_root or denied:
                    with self.assertRaises(ValueError): m.observe(args)
                    self.assertTrue((args.output_directory / "failure.json").is_file())
                    self.assertFalse((args.output_directory / "summary.json").exists())
                else:
                    result = m.observe(args)
                    self.assertFalse(result["root_deployment_authorized"])
                    self.assertTrue(result["root_application_absent"])
                if wrong_account or denied: self.assertEqual(len(calls), 1)

    def test_only_read_commands(self): self.run_observation()
    def test_wrong_account_stops_before_cluster_access(self): self.run_observation(wrong_account=True)
    def test_existing_root_rejected(self): self.run_observation(extra_root=True)
    def test_api_failure_is_not_absence(self): self.run_observation(denied=True)


if __name__ == "__main__":
    unittest.main()
