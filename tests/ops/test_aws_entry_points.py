"""Exercise backend interoperability and the independent stack entry point."""
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import aws_preflight
import aws_state
import deploy_aws_stack as stack
from configuration import EXAMPLE_CONFIG, OpsError


class EntryPointTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("terraform"), "requires terraform")
    def test_two_native_local_states_reopen_from_clean_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = ROOT / "infra/terraform/aws/environments/dev"
            def checkout(name):
                root = base / name
                root.mkdir()
                shutil.copy(fixture / "backend.tf", root)
                shutil.copy(fixture / "local_override.tf.example", root / "local_override.tf")
                (root / "main.tf").write_text('resource "terraform_data" "instance" {}\n')
                self.assertEqual(aws_preflight.backend_type(root), "local")
                return root
            def run(args, env):
                return subprocess.run(args, env=env, check=True, capture_output=True, text=True).stdout
            env = dict(os.environ, TF_WORKSPACE="default")
            one = checkout("first")
            command = ["terraform", "-chdir=" + str(one)]
            ids = {}
            for name in ("a", "b"):
                path = base / (name + ".tfstate")
                with self.subTest(name=name):
                    run(command + ["init", "-reconfigure", "-backend-config=path=" + str(path)], env)
                    run(command + ["apply", "-auto-approve"], env)
                    ids[name] = json.loads(run(command + ["state", "pull"], env))["lineage"]
            self.assertNotEqual(ids["a"], ids["b"])
            two = checkout("reopened")
            command = ["terraform", "-chdir=" + str(two)]
            settings = {"type": "local", "path": "a.tfstate"}
            aws_state.initialize_backend(run, command, env, two, settings, base)
            self.assertEqual(json.loads(run(command + ["state", "pull"], env))["lineage"], ids["a"])
            run(command + ["destroy", "-auto-approve"], env)
            other = json.loads((base / "b.tfstate").read_text())
            self.assertEqual(other["lineage"], ids["b"])
            self.assertEqual(other["resources"][0]["name"], "instance")

    @unittest.skipUnless(shutil.which("helm"), "requires helm")
    def test_release_has_timed_canary_and_inline_analysis_in_both_stages(self):
        chart = ROOT / "apps/demo-api/helm"
        for stage in ("dev", "test"):
            with self.subTest(stage=stage):
                args = ["helm", "template", "demo-api", str(chart), "--namespace", "startup-apps",
                        "-f", str(chart / f"values/environments/aws-{stage}.yaml"),
                        "-f", str(chart / f"values/releases/aws-{stage}.yaml")]
                docs = list(yaml.safe_load_all(subprocess.check_output(args, text=True)))
                workload = next(doc for doc in docs if doc and doc["kind"] == "Rollout")
                canary = workload["spec"]["strategy"]["canary"]
                self.assertEqual(canary["trafficRouting"]["alb"]["ingress"], "demo-api")
                steps = canary["steps"]
                templates = {doc["metadata"]["name"] for doc in docs if doc and doc["kind"] == "AnalysisTemplate"}
                analysis = next(i for i, step in enumerate(steps) if "analysis" in step)
                self.assertLess(analysis, steps.index({"setWeight": 100}))
                self.assertIn(steps[analysis]["analysis"]["templates"][0]["templateName"], templates)
                self.assertTrue(all(step["pause"].get("duration") for step in steps if "pause" in step))

    def test_standalone_uses_supplied_outputs_and_rejects_other_environment(self):
        for stage in ("dev", "test"):
            name = "startup-devops-baseline-" + stage
            values = dict(environment_name=stage, eks_cluster_name=name, eks_cluster_endpoint="https://eks.invalid",
                          database_mode="none", vpc_id="vpc-fixture", route53_hosted_zone_id="fixture",
                          demo_api_hostname=f"demo.{stage}.aureumstack.com", karpenter_controller_role_arn="karpenter",
                          aws_load_balancer_controller_role_arn="alb")
            def payload():
                return io.StringIO(json.dumps({k: {"value": v} for k, v in values.items()}))
            with self.subTest(stage=stage), patch.object(stack, "operator_cluster", return_value=Mock(context=name)) as identity, \
                    patch.object(stack, "lifecycle_lock", return_value=nullcontext(Path("/unused"))), \
                    patch.object(stack, "apply_outputs") as apply:
                stack.deploy_outputs(EXAMPLE_CONFIG, "aws-" + stage, payload())
                self.assertEqual(apply.call_args.args[3], values)
                self.assertEqual(apply.call_args.args[1]["gitops_root"], f"clusters/aws/profiles/{stage}-no-database/root-app.yaml")
                values["eks_cluster_name"] = "different-cluster"
                with self.assertRaisesRegex(OpsError, "selected overlay"):
                    stack.deploy_outputs(EXAMPLE_CONFIG, "aws-" + stage, payload())
                identity.assert_called_once()
                apply.assert_called_once()
