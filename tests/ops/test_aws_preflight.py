import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import aws_preflight as aws
import cli
import configuration


class AwsPreflightTests(unittest.TestCase):
    def test_personal_inputs_and_wrong_target_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            env = configuration.environment(configuration.DEFAULT_CONFIG, "aws-dev")
            env["terraform"].update(variables_file="vars.tfvars.json", backend_file="dev.tfbackend")
            inventory = folder / "environments.yaml"
            inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"aws-dev": env}}))
            account = env["aws"]["expected_account_id"]
            backend = folder / "dev.tfbackend"
            backend.write_text(f'bucket = "fixture-only"\nkey = "environments/dev/terraform.tfstate"\n'
                               f'region = "us-east-1"\nallowed_account_ids = ["{account}"]\n'
                               f'kms_key_id = "arn:aws:kms:us-east-1:{account}:key/test-key"\n'
                               'encrypt = true\nuse_lockfile = true\n')
            command = ["preflight", "--env", "aws-dev", "--config", str(inventory), "--check-inputs"]
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command), 1)
                self.assertIn("Missing input file", error.getvalue())
            values = {"enable_github_actions_runtime_identity": True, "eks_node_desired_size": 4,
                      "github_actions_runtime_role_arn": f"arn:aws:iam::{account}:role/startup-devops-baseline-dev-github-runtime-read-role",
                      "eks_public_access_cidrs": ["192.0.2.4/32"]}
            private = folder / "vars.tfvars.json"
            private.write_text(json.dumps(values))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(command), 0)
                report = json.loads(output.getvalue())
            self.assertEqual((report["scope"], report["live_checks"]), ("personal-files", "pending"))
            self.assertNotIn("192.0.2.4", output.getvalue())
            for key, value in (("environment", "test"), ("aws_region", "us-west-2"),
                               ("eks_public_access_cidrs", ["0.0.0.0/0"]), ("github_actions_runtime_role_arn", "wrong"),
                               ("enable_github_actions_runtime_identity", False)):
                private.write_text(json.dumps({**values, key: value}))
                with self.subTest(key=key), redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command), 1)
            backend.write_text(backend.read_text().replace("environments/dev/", "environments/test/"))
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command), 1)
                self.assertIn("backend key", error.getvalue())

    def test_template_backend_mismatch_reported_and_personal_test_refused(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["preflight", "--env", "aws-test"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["declared_backend"], "local")
        self.assertTrue(any("S3 backend file" in issue for issue in report["live_blockers"]))
        with redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(["preflight", "--env", "aws-test", "--check-inputs"]), 1)
        self.assertIn("root declares local state", error.getvalue())

    def test_dry_run_and_invalid_env_do_not_start_tools(self):
        with patch.object(aws.subprocess, "run") as tool, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["preflight", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertEqual(cli.main(["preflight", "--env", "local"]), 1)
            self.assertEqual(cli.main(["show", "--check-inputs"]), 1)
            tool.assert_not_called()

    def test_lost_rbac_binding_rejected(self):
        with self.assertRaisesRegex(configuration.OpsError, "Missing runtime group permission"):
            aws.check_bindings([], "argocd", "runtime", [("argoproj.io", "applications", "get")])
