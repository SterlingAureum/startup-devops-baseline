import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_destroy as teardown
import cli
from configuration import EXAMPLE_CONFIG, OpsError, environment


def resource(module, kind, name="this", **instance):
    return {"module": "module." + module, "type": kind, "name": name, "mode": "managed", "instances": [instance]}


class TeardownTests(unittest.TestCase):
    def test_only_deletable_dev_addresses_are_targeted(self):
        state = {"resources": [
            resource("cnpg_backup", "aws_s3_bucket"),
            resource("cnpg_backup", "aws_s3_bucket_versioning"),
            resource("external_secrets", "aws_secretsmanager_secret"),
            resource("cnpg_backup", "aws_iam_role"),
            resource("vpc", "aws_subnet", index_key="us-east-1a")]}
        delete, keep = teardown.partition(state)
        self.assertEqual(delete, {"module.cnpg_backup.aws_iam_role.this", 'module.vpc.aws_subnet.this["us-east-1a"]'})
        self.assertEqual(len(keep), 3)
        for module in ("runtime_identities", "state_bootstrap", "github_actions_runtime_identity[0]"):
            with self.assertRaises(OpsError):
                teardown.partition({"resources": [resource(module, "aws_iam_role")]})

    def test_unreviewed_actions_and_missing_targets_stop_before_cleanup(self):
        target = "module.eks.aws_eks_cluster.this"
        plan = {"resource_changes": [{"mode": "managed", "address": target, "change": {"actions": ["delete"]}}]}
        self.assertEqual(teardown.check_plan(plan, {target}), [target])
        with self.assertRaises(OpsError):
            teardown.check_plan(plan, {target, "module.vpc.aws_vpc.this"})
        with self.assertRaises(OpsError):
            teardown.check_plan(plan, {"module.vpc.aws_vpc.this"})
        plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]
        with self.assertRaises(OpsError):
            teardown.check_plan(plan, {target})

    def test_preview_dry_run_starts_no_tools(self):
        with patch.object(teardown, "destroy") as destroy, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "destroy", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertFalse(json.loads(output.getvalue())["executed"])
            destroy.assert_not_called()

    def test_test_alias_selects_test_state_and_requires_physical_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = folder / "inventory.yaml"
            entry = environment(EXAMPLE_CONFIG, "aws-test")
            config.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"sandbox": entry}}))
            cluster = "startup-devops-baseline-test"
            command = ["destroy", "--env", "sandbox", "--config", str(config), "--retain-backups"]
            with patch.object(teardown, "inspect", return_value={"cluster": cluster}) as inspect, \
                    patch.object(teardown.Cluster, "aws", return_value='{"Account":"123456789012"}') as aws, \
                    patch.object(teardown, "lifecycle_lock") as lock, \
                    patch.object(teardown, "check_selected_state") as check, patch.object(teardown, "session") as session, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command + ["--dry-run"]), 0)
                inspect.assert_not_called()
                self.assertEqual(cli.main(command + ["--confirm", "startup-devops-baseline-dev"]), 1)
                self.assertIn("--confirm " + cluster, error.getvalue())
                aws.assert_not_called()
                session.assert_not_called()
                for confirm in (None, cluster):
                    self.assertEqual(cli.main(command + (["--confirm", confirm] if confirm else [])), 0)
                    self.assertFalse(inspect.call_args.kwargs["check_network"])
                    target = inspect.call_args.args[0]
                    self.assertEqual((target.inventory_name, target.stage), ("sandbox", "test"))
                    self.assertEqual(check.call_args.args[-1], "destroy")
                    lock.assert_called_with("123456789012", "us-east-1", cluster)
                    g, env, path, confirmed, _, _, retain = session.call_args.args
                    self.assertEqual(g.context, cluster)
                    self.assertEqual(env["terraform"]["root"], "infra/terraform/aws/environments/test")
                    self.assertEqual(env["terraform"]["backend"]["config_file"], "aws-test.tfbackend")
                    self.assertEqual((path, confirmed, retain), (config, confirm, True))

    def test_foreign_dns_target_blocks(self):
        g = Mock()
        g.obj.return_value = {}
        g.aws.side_effect = [json.dumps({"ResourceRecordSets": [{"Type": "A", "Name": "dev.example."}]}),
                             '{"LoadBalancers":[]}']
        with self.assertRaisesRegex(OpsError, "DNS alias"):
            teardown.dns_record(g, {"route53_hosted_zone_id": "zone", "demo_api_hostname": "dev.example"})

    def test_snapshot_failure_stops_before_deleting_volumes(self):
        g = Mock()
        g.context = "test-dev"
        g.aws.side_effect = ['{"SnapshotId":"snap-1"}', '{"Snapshots":[{"State":"error"}]}']
        g.until.side_effect = lambda _, read: read()
        journal = {"snapshots": {}}
        save = Mock()
        with self.assertRaisesRegex(OpsError, "snapshot failed"):
            teardown.backup(g, {"vol-123": "data-platform/pg"}, journal, save)
        self.assertEqual(journal["snapshots"], {"vol-123": "snap-1"})
        save.assert_called_once()
        g.k.assert_not_called()

    def test_snapshot_resume_uses_saved_id(self):
        g = Mock()
        g.until.side_effect = lambda _, read: read()
        g.aws.return_value = '{"Snapshots":[{"State":"completed"}]}'
        teardown.backup(g, {"vol-ab": "data-platform/pg"}, {"snapshots": {"vol-ab": "snap-ab"}}, Mock())
        g.aws.assert_called_once_with("ec2", "describe-snapshots", "--snapshot-ids", "snap-ab")

    def test_session_previews_then_applies_only_after_cleanup(self):
        for stage in ("dev", "test"):
            with self.subTest(stage=stage):
                self.check_session_preview_and_apply(stage)

    def check_session_preview_and_apply(self, stage):
        g = Mock()
        g.context = "example-" + stage
        g.env = {"TF_VAR_environment": "unexpected"}
        aws = {"region": "us-east-1", "expected_account_id": "123456789012"}
        env = {"aws": aws, "terraform": {"root": "infra/terraform/aws/environments/" + stage,
                                         "backend": {"type": "s3", "config_file": stage + ".tfbackend"}, "variables_file": stage + ".tfvars"}}
        name = "module.eks.aws_eks_cluster.this"
        retained = resource("cnpg_backup", "aws_s3_bucket")
        state = {"lineage": "12345678-1234-1234-1234-123456789012",
                 "outputs": {k: {"value": v} for k, v in {
                     "eks_cluster_name": g.context, "eks_cluster_endpoint": "endpoint", "vpc_id": "vpc-1"}.items()},
                 "resources": [resource("eks", "aws_eks_cluster"), retained]}
        live = {"arn": "arn:aws:eks:us-east-1:123456789012:cluster/" + g.context, "endpoint": "endpoint",
                "resourcesVpcConfig": {"vpcId": "vpc-1"}}
        events = []
        def command(args, env):
            if args[0] == "terraform":
                self.assertNotIn("TF_VAR_environment", env)
                self.assertTrue(args[1].endswith("/environments/" + stage))
            if "init" in args:
                self.assertIn("-backend-config=" + str(folder / (stage + ".tfbackend")), args)
            if "pull" in args:
                if "apply" in events:
                    return json.dumps(dict(state, resources=[retained]))
                return json.dumps(state)
            if "show" in args:
                return json.dumps({"resource_changes": [{"mode": "managed", "address": name,
                                                         "change": {"actions": ["delete"]}}]})
            if "plan" in args:
                self.assertIn("-var-file=" + str(folder / (stage + ".tfvars")), args)
                self.assertEqual([a for a in args if a.startswith("-target=")], ["-target=" + name])
                events.append("plan")
            return ""
        g.aws.side_effect = lambda service, action, *args: json.dumps(
            {"clusters": [g.context]} if action == "list-clusters" else {"cluster": live})
        with tempfile.TemporaryDirectory() as tmp, patch.object(teardown, "run", side_effect=command), \
                patch.object(teardown, "demo_lbs", return_value=set()), \
                patch.object(teardown, "storage", return_value={}), patch.object(teardown, "dns_record", return_value=None), \
                patch.object(teardown, "remove_stack", side_effect=lambda *a: events.append("cleanup")), \
                patch.object(teardown.subprocess, "run", side_effect=lambda *a, **kw: events.append("apply")), \
                patch.object(teardown, "check_absent", side_effect=lambda *a: events.append("verify")), \
                redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            teardown.session(g, env, folder / "config", None, folder, tmp)
            self.assertEqual(events, ["plan"])
            teardown.session(g, env, folder / "config", g.context, folder, tmp)
            self.assertEqual(events, ["plan", "plan", "cleanup", "apply", "verify"])

    def test_interrupted_network_phase_resumes_with_saved_identity_and_a_fresh_plan(self):
        g = Mock(context="demo-dev", env={})
        eks = resource("eks", "aws_eks_cluster")
        vpc = resource("vpc", "aws_vpc", attributes={"id": "vpc-a"})
        held = resource("external_secrets", "aws_secretsmanager_secret")
        state = {"lineage": "12345678-1234-1234-1234-123456789012", "resources": [eks, vpc, held],
                 "outputs": {k: {"value": v} for k, v in {"eks_cluster_name": g.context,
                             "vpc_id": "vpc-a", "eks_cluster_endpoint": "endpoint"}.items()}}
        env = {"aws": {"region": "us-east-1", "expected_account_id": "123456789012"},
               "terraform": {"root": "dev", "backend": {"type": "s3", "config_file": "dev.backend"}, "variables_file": "dev.tfvars"}}
        plans, applies = [], []
        def terraform(args, env):
            if "pull" in args:
                return json.dumps(state)
            if "plan" in args:
                plans.append([a.removeprefix("-target=") for a in args if a.startswith("-target=")])
            if "show" in args:
                return json.dumps({"resource_changes": [{"address": a, "mode": "managed", "change": {"actions": ["delete"]}}
                                                       for a in plans[-1]]})
            return ""
        def apply(*args, **kwargs):
            applies.append(plans[-1])
            state["resources"].remove(eks if eks in state["resources"] else vpc)
        live = {"arn": "arn:aws:eks:us-east-1:123456789012:cluster/demo-dev", "endpoint": "endpoint",
                "resourcesVpcConfig": {"vpcId": "vpc-a", "clusterSecurityGroupId": "sg-a"}}
        def aws(svc, action, *args):
            if action == "list-clusters":
                return json.dumps({"clusters": [g.context] if eks in state["resources"] else []})
            return json.dumps({"cluster": live})
        g.aws.side_effect = aws
        with tempfile.TemporaryDirectory() as tmp, patch.object(teardown, "run", side_effect=terraform), \
                patch.object(teardown, "demo_lbs", return_value=[]), patch.object(teardown, "storage", return_value={}), \
                patch.object(teardown, "dns_record", return_value=None), patch.object(teardown, "remove_stack") as cleanup, \
                patch.object(teardown.subprocess, "run", side_effect=apply), patch.object(teardown, "check_absent"), \
                patch.object(teardown, "release_network", side_effect=[OpsError("interrupted"), None]) as release, \
                redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            args = (g, env, folder / "inventory")
            teardown.session(*args, None, folder, tmp)
            release.assert_not_called()
            self.assertFalse(applies)
            with self.assertRaisesRegex(OpsError, "interrupted"):
                teardown.session(*args, g.context, folder, tmp)
            self.assertEqual(applies, [[teardown.CLUSTER]])
            self.assertEqual(release.call_args.args[1]["cluster_sg"], "sg-a")
            teardown.session(*args, g.context, folder, tmp)
            cleanup.assert_called_once()
            self.assertEqual(applies, [[teardown.CLUSTER], ["module.vpc.aws_vpc.this"]])
            self.assertEqual(state["resources"], [held])

    def test_disposable_data_requires_matching_creation_plan(self):
        attrs = {"tags": {teardown.GENERATION: "first"}, "force_destroy": True}
        cluster = resource("eks", "aws_eks_cluster", attributes=attrs)
        bucket = resource("cnpg_backup", "aws_s3_bucket", attributes=attrs)
        settings = resource("cnpg_backup", "aws_s3_bucket_versioning")
        secret = resource("external_secrets", "aws_secretsmanager_secret", attributes=attrs)
        state = {"resources": [cluster, bucket, settings, secret]}
        owner = teardown.creation_plan(state)
        self.assertEqual(owner, "first")
        self.assertFalse(teardown.partition(state, owner)[1])
        for policy in [{"retain": True, "owner": owner}, {"owner": "next"}, {"owner": None}]:
            self.assertEqual(len(teardown.partition(state, **policy)[1]), 3)
        bucket["instances"][0]["attributes"] = dict(attrs, force_destroy=False)
        self.assertEqual(len(teardown.partition(state, owner)[1]), 2)

    def test_refreshed_marker_prevents_stale_deletion(self):
        change = {"address": teardown.SECRET, "mode": "managed", "change": {"actions": ["delete"], "before": {}}}
        with self.assertRaisesRegex(OpsError, "marker changed"):
            teardown.check_plan({"resource_changes": [change]}, {teardown.SECRET}, "old")

    def test_lb_progress_and_timeout_preserve_finalizers(self):
        g = Mock(timeout=60)
        g.obj.side_effect = [{"metadata": {"finalizers": ["ingress.k8s.aws/resources"]}},
                             {"status": {"availableReplicas": 1}}]
        with patch.object(teardown, "resources", return_value=[]), patch.object(teardown, "vpc_lbs", return_value=[]), \
                patch.object(teardown.time, "monotonic", side_effect=[0, 61]), \
                redirect_stdout(io.StringIO()) as log, self.assertRaisesRegex(OpsError, "before Terraform apply"):
            teardown.release_ingress(g, "vpc", set())
        self.assertIn("ingress.k8s.aws/resources", log.getvalue())
        self.assertIn("controllerAvailable=1", log.getvalue())
        self.assertIn("--wait=false", g.k.call_args.args)
        g.k.assert_called_once()
        g.aws.assert_not_called()

    def test_resume_after_ingress_deleted_waits_for_exact_alb(self):
        g = Mock(timeout=60)
        g.obj.return_value = None
        with patch.object(teardown, "resources", return_value=[]), \
                patch.object(teardown, "vpc_lbs", side_effect=[[{"LoadBalancerArn": "arn:old"}], []]), \
                patch.object(teardown.time, "sleep"), redirect_stdout(io.StringIO()):
            teardown.release_ingress(g, "vpc", {"arn:old"})
        with patch.object(teardown, "vpc_lbs", return_value=[{"LoadBalancerArn": "arn:other"}]), \
                self.assertRaisesRegex(OpsError, "arn:other"):
            teardown.release_ingress(g, "vpc", {"arn:old"})

    def test_unrelated_lb_blocks_before_any_delete(self):
        g = Mock(context="dev")
        g.obj.return_value = None
        lb = {"Type": "application", "LoadBalancerArn": "arn:other", "DNSName": "other.elb"}
        g.aws.return_value = json.dumps({"TagDescriptions": [{"ResourceArn": "arn:other", "Tags": []}]})
        with patch.object(teardown, "vpc_lbs", return_value=[lb]), self.assertRaisesRegex(OpsError, "other.elb"):
            teardown.demo_lbs(g, "dev-vpc")
        g.k.assert_not_called()

    def test_infra_only_cluster_skips_scale_but_checks_for_storage_and_network_dependencies(self):
        g = Mock(context="example-test", timeout=60)
        g.obj.return_value = None
        g.until.side_effect = lambda description, read: self.assertTrue(read())
        g.aws.side_effect = ['{"LoadBalancers":[]}', '{"ResourceRecordSets":[]}', '{"LoadBalancers":[]}',
                             '{"InstanceProfiles":[]}', '{"Reservations":[]}']
        with patch.object(teardown, "resources", return_value=[]) as listing, redirect_stdout(io.StringIO()):
            teardown.remove_stack(g, {"vpc_id": "vpc-test", "karpenter_node_role_name": "role-test",
                                      "route53_hosted_zone_id": "zone", "demo_api_hostname": "test.example"},
                                  {"snapshots": {}}, Mock(), False)
        self.assertNotIn("scale", [c.args[0] for c in g.k.call_args_list])
        self.assertTrue(any(c.args[1] == "pv" for c in listing.call_args_list))
        self.assertTrue(any("Name=vpc-id,Values=vpc-test" in c.args for c in g.aws.call_args_list))
        self.assertEqual(g.aws.call_count, 5)

    def test_controller_query_failure_stops_cleanup(self):
        g = Mock()
        g.obj.side_effect = OpsError("cannot read controller")
        with patch.object(teardown, "demo_lbs", return_value=set()), patch.object(teardown, "dns_record", return_value=None), \
                self.assertRaisesRegex(OpsError, "cannot read controller"):
            teardown.remove_stack(g, {"vpc_id": "vpc-test"}, {"snapshots": {}}, Mock(), False)
        g.k.assert_not_called()

    def test_default_releases_csi_volumes_without_creating_snapshots(self):
        g = Mock()
        journal = {"snapshots": {"vol-123": "snap-previous"}}
        g.obj.return_value = None
        g.until.side_effect = lambda description, read: read()
        g.aws.side_effect = ['{"InstanceProfiles":[]}', '{"Reservations":[]}', '{"Volumes":[]}']
        with patch.object(teardown, "demo_lbs", return_value=set()), patch.object(teardown, "dns_record", return_value=None), \
                patch.object(teardown, "storage", return_value={"vol-456": "observability/prom"}), \
                patch.object(teardown, "backup") as snapshot, patch.object(teardown, "release_ingress"), \
                patch.object(teardown, "resources", return_value=[]), redirect_stdout(io.StringIO()):
            teardown.remove_stack(g, {"vpc_id": "vpc", "karpenter_node_role_name": "role"}, journal, Mock(), False)
        snapshot.assert_not_called()
        self.assertEqual(journal["volumes"], ["vol-123", "vol-456"])
        self.assertIn("Name=volume-id,Values=vol-123,vol-456", g.aws.call_args.args)

    def test_redeploy_invalidates_old_cleanup_and_snapshot_checkpoint(self):
        journal = {"cleaned": True, "snapshots": {"vol-123": "snap-old"}}
        teardown.reopen_receipt(journal)
        self.assertEqual(journal["prior_snapshots"], ["snap-old"])
        self.assertEqual(journal["snapshots"], {})
        self.assertFalse(journal["cleaned"])
        self.assertIn("vol-123", journal["volumes"])

    def test_cli_forwards_opt_in_and_interrupt_returns_130(self):
        with patch.object(teardown, "destroy", side_effect=KeyboardInterrupt) as invoke:
            result = cli.main(["--config", str(EXAMPLE_CONFIG), "destroy", "--env", "aws-dev", "--retain-backups", "--confirm", "dev"])
        self.assertEqual(result, 130)
        self.assertEqual(invoke.call_args.args[-2:], ("dev", True))
        self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "deploy", "--env", "aws-dev", "--retain-backups", "--dry-run"]), 1)

    def test_external_secrets_finish_before_namespace_delete_and_retry_skips_absent(self):
        g = Mock(timeout=60)
        g.obj.return_value = {"metadata": {}}
        pending = [{"metadata": {"name": "example", "finalizers": ["external-secrets-cleanup"]}}]
        calls = []
        g.k.side_effect = lambda *args: calls.append(args)
        # Model one pending poll, successful finalization and a second invocation after interruption.
        with patch.object(teardown, "resources", side_effect=[pending, pending, [], []]), \
                patch.object(teardown.time, "sleep"), redirect_stdout(io.StringIO()):
            teardown.release_external_secrets(g)
            teardown.release_external_secrets(g)
        self.assertEqual(len(calls), 1)
        self.assertIn("externalsecrets.external-secrets.io", calls[0])
        self.assertIn("startup-apps", calls[0])

    def test_stuck_external_secret_blocks_namespace_deletion(self):
        g = Mock(timeout=30)
        g.obj.return_value = {"metadata": {}}
        g.until.side_effect = lambda description, done: done()
        pending = [{"metadata": {"name": "demo-api-postgresql", "finalizers": ["eso-cleanup"]}}]
        def resources(cluster, kind, *args):
            return pending if kind == "externalsecrets.external-secrets.io" else []
        with patch.object(teardown, "resources", side_effect=resources), \
                patch.object(teardown, "dns_record", return_value=None), patch.object(teardown, "demo_lbs"), \
                patch.object(teardown, "release_ingress"), patch.object(teardown, "storage", return_value={}), \
                patch.object(teardown.time, "monotonic", side_effect=[0, 31]), patch.object(teardown, "delete") as delete, \
                redirect_stdout(io.StringIO()), self.assertRaisesRegex(OpsError, "demo-api-postgresql.*eso-cleanup"):
            teardown.remove_stack(g, {"vpc_id": "vpc"}, {"snapshots": {}}, Mock(), False)
        delete.assert_not_called()
