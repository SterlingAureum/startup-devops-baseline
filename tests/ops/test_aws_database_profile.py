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
import aws_database as db
import aws_provision
import aws_deploy
import aws_destroy
import aws_preflight
import aws_state
import cli
from configuration import EXAMPLE_CONFIG, OpsError


class DevDatabaseProfileTests(unittest.TestCase):
    def test_preflight_selects_gitops_profile_and_one_terraform_root(self):
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
                self.assertEqual(root, ROOT / "infra/terraform/aws/environments/dev")
                self.assertTrue({"eks", "cnpg_backup_storage", "external_secrets_storage",
                                 "cnpg_backup_access", "external_secrets_access"} <= modules)
                overlay = Path(report["gitops_root"]).parent
                objects = aws_preflight.kustomize(overlay)
                profiles[mode] = {(d["kind"], d["metadata"]["name"]) for d in objects}
                dedicated = {("Application", "cloudnative-pg"), ("Application", "postgresql-baseline"),
                             ("NodePool", "database-ondemand"), ("NodePool", "database-recovery-ondemand"),
                             ("EC2NodeClass", "database")}
                if mode == "cnpg":
                    self.assertTrue(dedicated <= profiles[mode])
                else:
                    self.assertFalse(dedicated & profiles[mode])
                    self.assertIn(("Application", "external-secrets"), profiles[mode])
                    self.assertIn(("Application", "demo-api-aws-dev"), profiles[mode])
            self.assertLess(profiles["none"], profiles["cnpg"])

    def test_additive_transition_requires_provision_and_blocks_removal(self):
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
                if old == "cnpg":
                    with self.assertRaisesRegex(OpsError, "Removing an installed database"):
                        aws_state.check_selected_state(g, report, "up")
                else:
                    self.assertEqual(aws_state.check_selected_state(g, report, "up")["database_mode"], "none")
                    with self.assertRaisesRegex(OpsError, "Run plan then up"):
                        aws_state.check_selected_state(g, report, "deploy")
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

    def test_rebuild_preserves_all_eight_legacy_addresses_and_ownership_after_move(self):
        cluster, account, region = "sample-dev", "123456789012", "us-east-1"
        bucket = f"{cluster}-{account}-{region}-cnpg"
        name = cluster + "/demo-api/postgresql"
        attrs = {"id": bucket, "bucket": bucket, "name": name, "force_destroy": True,
                 "arn": f"arn:aws:secretsmanager:{region}:{account}:secret:{name}-abcdef",
                 "tags": {"BaselineDevCreationPlan": "older"}}
        g = Mock(context=cluster)
        resources = []
        for address in sorted(db.DURABLE):
            module, kind, key = address.rsplit(".", 2)
            resources.append({"module": module, "mode": "managed", "type": kind, "name": key,
                              "instances": [{"attributes": attrs.copy()}]})
        state = {"version": 4, "serial": 85, "lineage": "080a7801-0ed1-4582-9e9d-9a520a812356",
                 "outputs": {"database_mode": {"value": "cnpg"}}, "resources": resources}
        report = {"stage": "dev", "environment": "aws-dev", "expected_account_id": account,
                  "region": region, "declared_backend": "local", "database_mode": "none"}
        hcl_moves = aws_preflight.read_inputs(ROOT / "infra/terraform/aws/environments/dev/database-moves.tf")["moved"]
        self.assertEqual({r["from"][2:-1]: r["to"][2:-1] for r in hcl_moves}, db.DEV_MOVES)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "state"
            report["state_address"] = str(file)
            for moved in (False, True):
                if moved:
                    for r in resources:
                        address = ".".join((r["module"], r["type"], r["name"]))
                        r["module"] = db.DEV_MOVES[address].rsplit(".", 2)[0]
                file.write_text(json.dumps(state))
                with redirect_stdout(io.StringIO()):
                    summary = aws_state.check_selected_state(g, report, "plan")
                self.assertEqual(summary["managed_instances"], 8)
                self.assertTrue(summary["retained_only"])
                self.assertEqual(summary.get("legacy_database_addresses", False), not moved)
                self.assertEqual(db.dev_variables("dev", "none", summary), ["-var=database_mode=none",
                                 "-var=retained_database_bucket=true", "-var=retained_database_secret=true"])
                targets, keep = aws_destroy.partition(state, owner="new")
                self.assertEqual(targets, set())
                self.assertEqual({db.original(a) for a in keep}, db.DURABLE)
                self.assertEqual(len(aws_destroy.partition(state, owner="older")[0]), 8)
            # A single additional managed address disqualifies a retained-only state.
            resources.append({"module": "module.vpc", "type": "aws_subnet", "name": "private",
                              "instances": [{"attributes": {}}], "mode": "managed"})
            state["outputs"]["eks_cluster_name"] = {"value": cluster}
            file.write_text(json.dumps(state))
            with self.assertRaisesRegex(OpsError, "Removing an installed database"):
                aws_state.check_selected_state(g, report, "plan")

    def test_retention_refuses_recreation_and_non_tag_edits_during_none_plan(self):
        address = db.DEV_MOVES[db.BUCKET]
        item = {"address": address, "mode": "managed", "change": {"actions": ["create"]}}
        plan = {"variables": {"database_mode": {"value": "none"}}, "resource_changes": [item]}
        with self.assertRaisesRegex(OpsError, "storage missing"):
            aws_provision.check_plan(plan, Mock())
        item["change"] = {"actions": ["update"], "before": {"force_destroy": False}, "after": {"force_destroy": True}}
        with self.assertRaisesRegex(OpsError, "Review changes"):
            aws_provision.check_plan(plan, Mock())

    def test_addition_waits_for_eso_before_switching_the_demo_and_resumes(self):
        root = yaml.safe_load((ROOT / "clusters/aws/overlays/dev/root-app.yaml").read_text())
        apps = aws_preflight.kustomize(aws_deploy.DB_PREPARE)
        children = {app["metadata"]["name"]: app for app in apps if app["kind"] == "Application"}
        self.assertIn("postgresql-baseline", children)
        self.assertFalse(children["demo-api-aws-dev"]["spec"]["source"]["helm"]["valuesObject"]["database"]["enabled"])
        g = Mock()
        g.k.return_value = '{"items":[]}'
        for path in ("clusters/aws/profiles/dev-no-database", aws_deploy.DB_PREPARE, "foreign"):
            live = json.loads(json.dumps(root))
            live["spec"]["source"]["path"] = path
            g.obj.side_effect = [{"kind": "CRD"}, live]
            if path == "foreign":
                with self.assertRaisesRegex(OpsError, "Unexpected live root"):
                    aws_deploy.check_deploy_target(g, root, children)
            else:
                self.assertTrue(aws_deploy.check_deploy_target(g, root, children))
        with patch.object(aws_deploy, "gitops") as stage, patch.object(aws_deploy, "seed_database") as seed, \
                patch.object(aws_deploy, "refresh_consumers") as refresh, patch.object(aws_deploy, "reconcile_dns"):
            seed.side_effect = OpsError("credential pending")
            with self.assertRaisesRegex(OpsError, "credential pending"):
                aws_deploy.enable_database(g, root, children, {}, "manifest", None)
            self.assertEqual(stage.call_args.args[1]["spec"]["source"]["path"], aws_deploy.DB_PREPARE)
            g.apply.assert_not_called()
            seed.side_effect = None
            seed.return_value = "version"
            aws_deploy.enable_database(g, root, children, {}, "manifest", None)
            g.apply.assert_called_once_with(root)
            refresh.assert_called_once_with(g, "version")

    def test_online_add_requires_existing_cluster_and_vpc_in_saved_plan(self):
        g = Mock(context="sample-dev")
        before = {"name": g.context, "tags": {"BaselineDatabaseMode": "none"}}
        after = {"name": g.context, "tags": {"BaselineDatabaseMode": "cnpg"}}
        eks = {"address": aws_destroy.CLUSTER, "mode": "managed",
               "change": {"actions": ["update"], "before": before, "after": after}}
        vpc = {"address": "module.vpc.aws_vpc.this", "mode": "managed",
               "change": {"actions": ["no-op"], "before": {"id": "vpc-example"}}}
        plan = {"resource_changes": [eks, vpc]}
        self.assertEqual(aws_provision.check_plan(plan, g, adding_database=True), "vpc-example")
        for row in (eks, vpc):
            previous = row["change"]["actions"]
            row["change"]["actions"] = ["create"]
            with self.assertRaisesRegex(OpsError, "existing EKS cluster and VPC"):
                aws_provision.check_plan(plan, g, adding_database=True)
            row["change"]["actions"] = previous

    def test_rebuilt_dev_archive_uses_new_prefix_and_existing_destinations_survive(self):
        g = Mock()
        root = "s3://example/postgresql-baseline"
        out = {"cnpg_backup_bucket_name": "example", "environment_name": "dev",
               "eks_cluster_endpoint": "https://example.invalid"}
        def configure(current):
            g.exists.return_value = {"spec": {"configuration": {"destinationPath": current}}}
            g.k.reset_mock()
            with patch.object(aws_deploy, "wait_for_cnpg"):
                aws_deploy.configure_database(g, out)
        configure("s3://__CNPG_BACKUP_BUCKET__/postgresql-baseline")
        new = json.loads(g.k.call_args.args[-1])[1]["value"]
        self.assertRegex(new, "^" + root + "/[a-f0-9]{20}$")
        for existing in (root, new):
            configure(existing)
            g.k.assert_not_called()
        with self.assertRaisesRegex(OpsError, "Unexpected live backup"):
            configure("s3://unrelated/postgresql-baseline")
