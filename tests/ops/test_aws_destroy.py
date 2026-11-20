import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_destroy as teardown
import cli
from configuration import OpsError


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
            self.assertEqual(cli.main(["destroy", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertFalse(json.loads(output.getvalue())["executed"])
            destroy.assert_not_called()

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
        g = Mock()
        g.context = "example-dev"
        g.env = {}
        aws = {"region": "us-east-1", "expected_account_id": "123456789012"}
        env = {"aws": aws, "terraform": {"root": "infra/terraform/aws/environments/dev",
                                         "backend_file": "dev.tfbackend", "variables_file": "dev.tfvars"}}
        name = "module.eks.aws_eks_cluster.this"
        retained = resource("cnpg_backup", "aws_s3_bucket")
        state = {"lineage": "12345678-1234-1234-1234-123456789012",
                 "outputs": {k: {"value": v} for k, v in {
                     "eks_cluster_name": "example-dev", "eks_cluster_endpoint": "endpoint", "vpc_id": "vpc-1"}.items()},
                 "resources": [resource("eks", "aws_eks_cluster"), retained]}
        live = {"arn": "arn:aws:eks:us-east-1:123456789012:cluster/example-dev", "endpoint": "endpoint",
                "resourcesVpcConfig": {"vpcId": "vpc-1"}}
        events = []
        def command(args, env):
            if "pull" in args:
                if "apply" in events:
                    return json.dumps(dict(state, resources=[retained]))
                return json.dumps(state)
            if "show" in args:
                return json.dumps({"resource_changes": [{"mode": "managed", "address": name,
                                                         "change": {"actions": ["delete"]}}]})
            if "plan" in args:
                self.assertEqual([a for a in args if a.startswith("-target=")], ["-target=" + name])
                events.append("plan")
            return ""
        g.aws.side_effect = lambda service, action, *args: json.dumps(
            {"clusters": [g.context]} if action == "list-clusters" else {"cluster": live})
        with tempfile.TemporaryDirectory() as tmp, patch.object(teardown, "run", side_effect=command), \
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
