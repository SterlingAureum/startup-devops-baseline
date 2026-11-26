import io
import json
from contextlib import nullcontext, redirect_stdout, redirect_stderr
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import aws_deploy
import aws_destroy
import aws_preflight
import aws_state
import cli
from configuration import EXAMPLE_CONFIG, OpsError


class DevDatabaseProfileTests(unittest.TestCase):
    def test_preflight_selects_complete_profile_and_preserves_terraform_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "env.yaml"
            doc = yaml.safe_load(EXAMPLE_CONFIG.read_text())
            entry = doc["environments"]["aws-dev"]
            profiles = {}
            for mode in ("cnpg", "none"):
                entry["database"] = {"mode": mode}
                inventory.write_text(yaml.safe_dump(doc))
                with redirect_stdout(io.StringIO()) as log:
                    self.assertEqual(cli.main(["preflight", "--env", "aws-dev", "--config", str(inventory)]), 0)
                report = json.loads(log.getvalue())
                self.assertEqual(report["database_mode"], mode)
                root = ROOT / report["terraform_execution_root"]
                modules = {name for file in root.glob("*.tf") for item in aws_preflight.read_inputs(file).get("module", [])
                           for name in item}
                self.assertIn("eks", modules)
                overlay = Path(report["gitops_root"]).parent
                objects = aws_preflight.kustomize(overlay)
                profiles[mode] = {(d["kind"], d["metadata"]["name"]) for d in objects}
                dedicated = {("Application", "cloudnative-pg"), ("Application", "postgresql-baseline"),
                             ("NodePool", "database-ondemand"), ("NodePool", "database-recovery-ondemand"),
                             ("EC2NodeClass", "database")}
                if mode == "cnpg":
                    self.assertTrue({"cnpg_backup", "external_secrets"} <= modules)
                    self.assertTrue(dedicated <= profiles[mode])
                else:
                    self.assertFalse({"cnpg_backup", "external_secrets"} & modules)
                    self.assertFalse(dedicated & profiles[mode])
                    self.assertIn(("Application", "external-secrets"), profiles[mode])
                    self.assertIn(("Application", "demo-api-aws-dev"), profiles[mode])
            self.assertLess(profiles["none"], profiles["cnpg"])

    def test_legacy_and_existing_modes_block_in_place_changes_but_allow_destroy(self):
        name = "sample-dev"
        g = Mock(context=name)
        report = {"stage": "dev", "environment": "sample", "expected_account_id": "123456789012",
                  "region": "us-east-1", "declared_backend": "local", "database_mode": "none"}
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "state"
            report["state_address"] = str(file)
            attrs = {"arn": f"arn:aws:eks:us-east-1:123456789012:cluster/{name}"}
            state = {"version": 4, "serial": 1, "lineage": "080a7801-0ed1-4582-9e9d-9a520a812356",
                     "outputs": {}, "resources": [{"mode": "managed", "type": "aws_eks_cluster",
                                                   "instances": [{"attributes": attrs}]}]}
            for old, selected in (("cnpg", "none"), ("none", "cnpg")):
                if old == "none":
                    attrs["tags"] = {"BaselineDatabaseMode": old}
                report["database_mode"] = selected
                file.write_text(json.dumps(state))
                with self.assertRaisesRegex(OpsError, "Existing state uses database.mode=" + old):
                    aws_state.check_selected_state(g, report, "up")
                self.assertEqual(aws_state.check_selected_state(g, report, "destroy")["database_mode"], old)

    def test_destroy_uses_recorded_profile_even_if_inventory_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            doc = yaml.safe_load(EXAMPLE_CONFIG.read_text())
            for recorded, selected in (("none", "cnpg"), ("cnpg", "none")):
                doc["environments"]["aws-dev"]["database"] = {"mode": selected}
                inventory.write_text(yaml.safe_dump(doc))
                with patch.object(aws_destroy, "inspect_infrastructure", return_value=({"cluster": "demo-dev"}, {})), \
                        patch.object(aws_destroy.Cluster, "aws", return_value='{"Account":"123456789012"}'), \
                        patch.object(aws_destroy, "lifecycle_lock", return_value=nullcontext(Path(tmp))), \
                        patch.object(aws_destroy, "check_selected_state", return_value={"database_mode": recorded}), \
                        patch.object(aws_destroy, "session") as session:
                    self.assertEqual(cli.main(["destroy", "--config", str(inventory), "--env", "aws-dev"]), 0)
                    self.assertEqual(session.call_args.kwargs["database_mode"], recorded)
            doc["environments"]["aws-test"]["database"] = {"mode": "none"}
            inventory.write_text(yaml.safe_dump(doc))
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(["up", "--dry-run", "--env", "aws-test", "--config", str(inventory)]), 1)
                self.assertIn("no database-free profile", error.getvalue())

    def test_light_bootstrap_installs_shared_components_and_skips_database_waits(self):
        out = {"database_mode": "none", "aws_load_balancer_controller_role_arn": "alb", "karpenter_controller_role_arn": "karp"}
        g = Mock()
        g.obj.return_value = None
        aws_deploy.prepare(g, out)
        self.assertEqual(g.irsa.call_count, 2)
        self.assertNotIn("data-platform", [call.args[0] for call in g.namespace.call_args_list])
        root = {"metadata": {"name": "root"}}
        children = {"aws-load-balancer-controller": {"spec": {"source": {"helm": {"valuesObject": {}}}}}}
        with patch.object(aws_deploy, "configure_database") as database:
            names = aws_deploy.gitops(g, root, children, dict(out, vpc_id="vpc"), "manifest")
            self.assertEqual(names, {"root", "aws-load-balancer-controller"})
            database.assert_not_called()
