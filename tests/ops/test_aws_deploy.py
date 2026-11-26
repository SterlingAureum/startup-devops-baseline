import base64
import io
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_deploy as deploy
import aws_standard_demo as demo
import cli
from configuration import EXAMPLE_CONFIG, OpsError, load_yaml


class AwsDeployTests(unittest.TestCase):
    def test_deploy_dry_run_does_not_contact_cloud(self):
        with patch.object(deploy, "deploy") as invoke, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "deploy", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertIn("refresh dedicated kubeconfig", json.loads(output.getvalue())["steps"])
            invoke.assert_not_called()

    def test_wait_on_older_client_and_fail_on_forbidden(self):
        cluster = deploy.Cluster("example", {}, 60, Path("/fixture/config"))
        with patch.object(cluster, "k", side_effect=["", '{"kind":"Secret"}']) as k, patch("time.sleep"):
            self.assertEqual(cluster.exists("data-platform", "secret/db")["kind"], "Secret")
            self.assertIn("--ignore-not-found", k.call_args.args)
        with patch.object(cluster, "k", side_effect=OpsError("Forbidden")):
            with self.assertRaisesRegex(OpsError, "Forbidden"):
                cluster.exists("data-platform", "secret/db")

    def test_credential_promotion_and_adoption(self):
        for labels, adopt, allowed in [({}, None, True), ({"old": ["AWSCURRENT", demo.BOOTSTRAP]}, None, True),
                                      ({"old": ["AWSCURRENT"]}, None, False),
                                      ({"old": ["AWSCURRENT"]}, "old", True),
                                      ({"old": ["AWSCURRENT"]}, "changed", False)]:
            with self.subTest(labels=labels, adopt=adopt):
                g = Mock()
                metadata = {"ARN": "arn", "Name": "demo", "VersionIdsToStages": labels}
                g.aws.side_effect = lambda service, action, *args, **kw: json.dumps({
                    "describe-secret": metadata, "get-secret-value": {"SecretString": '{"DATABASE_URL":"old","other":42}'}
                }.get(action, {}))
                if not allowed:
                    with self.assertRaises(OpsError):
                        demo.database_version(g, "arn", "demo", "postgresql://fixture", adopt)
                    self.assertFalse(any(c.args[1] == "put-secret-value" for c in g.aws.call_args_list))
                    continue
                version = demo.database_version(g, "arn", "demo", "postgresql://fixture", adopt)
                put, move = g.aws.call_args_list[-2:]
                self.assertTrue(put.kwargs["private"])
                self.assertNotIn("postgresql://fixture", put.args)
                self.assertEqual(json.loads(put.kwargs["data"])["DATABASE_URL"], "postgresql://fixture")
                if labels:
                    self.assertEqual(json.loads(put.kwargs["data"])["other"], 42)
                    self.assertEqual(move.args[-2:], ("--remove-from-version-id", "old"))
                else:
                    self.assertNotIn("--remove-from-version-id", move.args)
                self.assertIn(version, move.args)

    def test_first_version_may_already_be_current_and_failed_compare_preserves_operator(self):
        g = Mock()
        metadata = {"ARN": "arn", "Name": "demo", "VersionIdsToStages": {}}
        g.aws.side_effect = [json.dumps(metadata), '{"VersionStages":["AWSCURRENT","BASELINE_BOOTSTRAP"]}']
        demo.database_version(g, "arn", "demo", "first", None)
        self.assertEqual(g.aws.call_count, 2)
        g.reset_mock()
        metadata["VersionIdsToStages"] = {"old": ["AWSCURRENT", demo.BOOTSTRAP]}
        g.aws.side_effect = [json.dumps(metadata), json.dumps({"SecretString": '{"DATABASE_URL":"old"}'}),
                             '{}', OpsError("stage owner changed")]
        with self.assertRaisesRegex(OpsError, "stage owner changed"):
            demo.database_version(g, "arn", "demo", "new", None)
        self.assertEqual(g.aws.call_args.args[-2:], ("--remove-from-version-id", "old"))
        self.assertEqual(g.aws.call_count, 4)

    def test_rotation_and_equal_value(self):
        g = Mock()
        metadata = {"ARN": "arn", "Name": "demo", "VersionIdsToStages": {"old": ["AWSCURRENT", demo.BOOTSTRAP]},
                    "RotationEnabled": True}
        for desired in ("same", "new"):
            g.aws.side_effect = [json.dumps(metadata), json.dumps({"SecretString": '{"DATABASE_URL":"same"}'})]
            if desired == "new":
                with self.assertRaisesRegex(OpsError, "rotation"):
                    demo.database_version(g, "arn", "demo", desired, None)
            else:
                self.assertEqual(demo.database_version(g, "arn", "demo", desired, None), "old")

    def test_eso_waits_for_actual_target_data_before_restart(self):
        g = Mock()
        value = base64.b64encode(b"postgresql://fixture").decode()
        g.exists.return_value = {"data": {"fqdn-uri": value}}
        g.context = "example-dev"
        name = "example-dev/demo-api/postgresql"
        external = {"spec": {"secretStoreRef": {"kind": "SecretStore", "name": "aws-secrets-manager"}, "target": {"name": "demo-api-postgresql"}, "data": [{"secretKey": "DATABASE_URL",
                    "remoteRef": {"key": name, "property": "DATABASE_URL", "version": "AWSCURRENT"}}]}}
        g.obj.side_effect = [{"data": {"DATABASE_URL": "old"}}, {"data": {"DATABASE_URL": value}}, {}, g.exists.return_value]
        def wait(description, read):
            self.assertFalse(read())
            self.assertTrue(read())
        g.until.side_effect = wait
        g.aws.return_value = '{"VersionIdsToStages":{"current":["AWSCURRENT"]}}'
        with patch.object(demo, "database_version", return_value="current"), \
                patch.object(demo, "wait_for_consumer", return_value=external), patch.object(demo, "refresh_consumers") as restart:
            demo.seed_database(g, {"external_secrets_secret_name": name, "external_secrets_secret_arn": "arn"})
            restart.assert_called_once_with(g, "current")

    def test_workload_restart_is_versioned_and_idempotent_for_both_kinds(self):
        for is_rollout in (True, False):
            g = Mock()
            template = {"metadata": {"annotations": {}}, "spec": {"containers": [{"env": [{"name": "DATABASE_URL",
                        "valueFrom": {"secretKeyRef": {"name": "demo-api-postgresql", "key": "DATABASE_URL"}}}]}]}}
            workload = {"metadata": {"resourceVersion": "1", "generation": 6}, "spec": {"replicas": 1, "template": template},
                        "status": {"observedGeneration": "6", "replicas": 1, "readyReplicas": 1, "updatedReplicas": 1,
                                   "phase": "Healthy"}}
            kind = "rollouts.argoproj.io/demo-api" if is_rollout else "deployment.apps/demo-api"
            g.obj.side_effect = lambda ns, k: workload if k == kind or (is_rollout and k.startswith("crd/")) else None
            def patch_template(*args):
                self.assertIn(kind, args)
                changes = json.loads(args[-1])
                self.assertEqual(changes["metadata"]["resourceVersion"], "1")
                template["metadata"].update(changes["spec"]["template"]["metadata"])
            g.k.side_effect = patch_template
            def wait(description, read):
                result = read()
                self.assertTrue(result)
                return result
            g.until.side_effect = wait
            demo.refresh_consumers(g, "current")
            demo.refresh_consumers(g, "current")
            g.k.assert_called_once()

    def test_manual_canary_pause_waits_for_operator_without_mutating_rollout(self):
        g = Mock(context="cluster-test", path=Path("/tmp/test-config"))
        kind = "rollouts.argoproj.io/demo-api"
        workload = {
            "metadata": {"generation": 3},
            "spec": {"replicas": 2, "template": {"metadata": {"annotations": {demo.MARKER: "v1"}},
                     "spec": {"containers": [{"env": [{"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {
                         "name": "demo-api-postgresql", "key": "DATABASE_URL"}}}]}]}},
                     "strategy": {"canary": {"steps": [{"setWeight": 50}, {"pause": {"duration": "60s"}}, {"pause": {}}]}}},
            "status": {"observedGeneration": "3", "readyReplicas": 2, "updatedReplicas": 2,
                       "replicas": 2, "phase": "Paused", "currentStepIndex": 1},
        }
        g.obj.side_effect = lambda ns, k: workload if k == kind or k.startswith("crd/") else None
        def wait(description, read):
            if description == "standard demo database consumer":
                return read()
            self.assertFalse(read())  # Timed pause.
            self.assertNotIn("awaits manual promotion", log.getvalue())
            self.assertIn("timed pause=60s", log.getvalue())
            workload["status"]["currentStepIndex"] = 2
            self.assertFalse(read())
            self.assertFalse(read())
            self.assertEqual(log.getvalue().count("awaits manual promotion"), 1)
            self.assertIn("canary step 3/3, target weight=50%", log.getvalue())
            self.assertIn("promote demo-api --kubeconfig /tmp/test-config --context cluster-test", log.getvalue())
            workload["status"]["phase"] = "Healthy"
            self.assertTrue(read())
        g.until.side_effect = wait
        with redirect_stdout(io.StringIO()) as log:
            demo.refresh_consumers(g, "v1")
        g.k.assert_not_called()

    def test_current_rollout_failure_reports_analysis_and_ignores_stale_generation(self):
        g = deploy.Cluster("sample-test", {}, 60, Path("/fixture/test"))
        kind = "rollouts.argoproj.io/demo-api"
        spec = {"template": {"metadata": {"annotations": {demo.MARKER: "v1"}}},
                "strategy": {"canary": {"steps": [{"analysis": {}}]}}}
        status = {"phase": "Degraded", "abort": True, "currentStepIndex": 0, "canary": {
            "currentStepAnalysisRunStatus": {"name": "demo-check", "status": "Failed"}}}
        def snapshot(observed):
            return {"metadata": {"generation": 2}, "spec": spec, "status": dict(status, observedGeneration=observed)}
        with patch.object(g, "obj", side_effect=[snapshot("1"), snapshot("2")]), patch("time.sleep") as sleep:
            with self.assertRaises(OpsError) as failure:
                demo.wait_for_replicas(g, kind, "v1")
        sleep.assert_called_once()
        self.assertIn("Rollout controller reported failure", str(failure.exception))
        self.assertIn("AnalysisRun=demo-check (Failed)", str(failure.exception))
        self.assertIn("--context sample-test -n startup-apps describe", str(failure.exception))

    def test_inconclusive_analysis_times_out_with_last_observation(self):
        g = deploy.Cluster("sample-test", {}, 10, Path("/fixture/test"))
        spec = {"template": {"metadata": {"annotations": {demo.MARKER: "v1"}}},
                "strategy": {"canary": {"steps": [{"analysis": {}}]}}}
        workload = {"metadata": {"generation": 1}, "spec": spec, "status": {"observedGeneration": 1,
                    "phase": "Paused", "currentStepIndex": 0, "pauseConditions": [{"reason": "InconclusiveAnalysisRun"}]}}
        with patch.object(g, "obj", return_value=workload), patch("time.monotonic", side_effect=[0, 0, 0, 0, 10, 10]), \
                patch("time.sleep"), self.assertRaises(OpsError) as failure:
            demo.wait_for_replicas(g, "rollouts.argoproj.io/demo-api", "v1")
        detail = str(failure.exception)
        self.assertIn("Timed out:", detail)
        self.assertIn("timeout 10s", detail)
        self.assertIn("pause=InconclusiveAnalysisRun", detail)
        self.assertIn("get analysisruns.argoproj.io", detail)
        self.assertNotIn("promote demo-api", detail)

    def test_dns_existing_foreign_alias_is_preserved(self):
        g = Mock()
        g.until.return_value = "dev.elb.amazonaws.com"
        g.aws.side_effect = [
            json.dumps({"LoadBalancers": [{"DNSName": g.until.return_value, "VpcId": "v", "Type": "application",
                                            "CanonicalHostedZoneId": "alb-zone"}]}),
            json.dumps({"ResourceRecordSets": [{"Name": "demo.example.", "Type": "A", "ResourceRecords": []}]}),
        ]
        with self.assertRaisesRegex(OpsError, "points elsewhere"):
            demo.reconcile_dns(g, {"demo_api_hostname": "demo.example", "vpc_id": "v", "route53_hosted_zone_id": "zone"})
        self.assertEqual(g.aws.call_count, 2)

    def test_deploy_entry_rebuild_and_blocked_redeploy(self):
        self.check_deploy_entry("dev", "deploy")
        self.check_deploy_entry("test", "deploy")
        self.check_deploy_entry("test", "up")
        self.check_deploy_entry("dev", "up", mode="none")

    def check_deploy_entry(self, stage, command, mode="cnpg"):
        report = {"stage": stage, "cluster": f"startup-devops-baseline-{stage}",
                  "gitops_root": f"clusters/aws/overlays/{stage}/root-app.yaml"}
        if mode == "none":
            report.update(database_mode=mode, gitops_root="clusters/aws/profiles/dev-no-database/root-app.yaml")
        name = report["cluster"]
        out = {"environment_name": stage, "eks_cluster_name": name, "eks_cluster_endpoint": "https://eks",
               "vpc_id": "vpc-1"}
        if mode == "none":
            out["database_mode"] = mode
        def aws(*args):
            if args[:2] == ("sts", "get-caller-identity"):
                return '{"Account":"123456789012"}'
            return '{"cluster":{"status":"ACTIVE","endpoint":"https://eks","resourcesVpcConfig":{"vpcId":"vpc-1"}}}'

        def run(args, env, private=False):
            if args[0] == "aws":
                return json.dumps({"current-context": name, "clusters": [{"cluster": {"server": "https://eks"}}]})
            if "output" in args:
                return json.dumps({key: {"value": value} for key, value in out.items()})
            if "init" in args:
                return ""
            self.fail("Unexpected command: " + str(args))

        for scenario in ("fresh", "deleting namespace", "deleting root"):
            with self.subTest(stage=stage, command=command, scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                entry = load_yaml(EXAMPLE_CONFIG.read_text())["environments"][f"aws-{stage}"]
                manifest = "https://example.invalid/aws-install.yaml"
                entry["argocd"] = {"manifest": manifest}
                entry["database"] = {"mode": mode}
                inventory = folder / "personal.yaml"
                inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"team": entry}}))
                if scenario != "fresh":
                    (folder / "prior.json").write_text("preserve checkpoint")

                def kubectl(*args):
                    if "namespaces" in args:
                        target = "startup-apps" if scenario == "deleting namespace" else "unrelated"
                        return json.dumps({"items": [{"metadata": {"name": target, "deletionTimestamp": "now"}}]})
                    if "crd/applications.argoproj.io" in args:
                        return '{"kind":"CustomResourceDefinition"}' if scenario == "deleting root" else ""
                    if f"applications.argoproj.io/startup-devops-aws-{stage}-root" in args:
                        return '{"metadata":{"deletionTimestamp":"now"}}'
                    if "nodes" in args:
                        return ""
                    self.fail("Unexpected kubectl arguments: " + str(args))

                with patch.object(deploy, "check_selected_state"), patch.object(deploy, "inspect", return_value=report), \
                        patch.object(deploy, "lifecycle_lock", return_value=nullcontext(folder)), \
                        patch.object(deploy, "aws_private_path", return_value=folder / "kubeconfig"), \
                        patch.object(deploy, "run", side_effect=run), \
                        patch.object(deploy.Cluster, "aws", side_effect=aws), \
                        patch.object(deploy.Cluster, "k", side_effect=kubectl), \
                        patch.object(deploy, "provision") as provision, patch.object(deploy, "prepare") as prepare, patch.object(deploy, "gitops") as gitops, \
                        patch.object(demo, "seed_database") as seed, patch.object(demo, "reconcile_dns") as dns, \
                        patch.object(deploy, "check_apps") as verify, redirect_stdout(io.StringIO()) as log, \
                        redirect_stderr(io.StringIO()) as errors:
                    confirm = ["--confirm", name] if command == "up" else []
                    result = cli.main(["--config", str(inventory), command, "--env", "team", *confirm])
                    self.assertEqual(provision.called, command == "up")
                    self.assertIn(f"Dedicated kubeconfig: {folder / 'kubeconfig'}", log.getvalue())
                    if scenario == "fresh":
                        self.assertIn(deploy.kubectl_hint(folder / "kubeconfig", name), log.getvalue())
                        self.assertEqual(result, 0)
                        cluster, root, children, outputs, install = gitops.call_args.args
                        self.assertEqual(install, manifest)
                        self.assertEqual(cluster.context, name)
                        self.assertEqual(root["spec"]["source"]["path"], str(Path(report["gitops_root"]).parent))
                        self.assertEqual(outputs["eks_cluster_name"], name)
                        child = children[f"demo-api-aws-{stage}"]["spec"]
                        self.assertEqual(child["source"]["helm"]["valueFiles"], [
                            f"values/environments/aws-{stage}.yaml", f"values/releases/aws-{stage}.yaml"])
                        for kind in ("Rollout", "Deployment"):
                            self.assertTrue(any(rule["kind"] == kind and rule.get("jsonPointers") ==
                                                ["/spec/template/metadata/annotations/platform.startup.dev~1demo-db-version"]
                                                for rule in child["ignoreDifferences"]))
                        grafana = children[f"monitoring-aws-{stage}"]["spec"]["source"]["helm"]["valuesObject"]["grafana"]
                        self.assertEqual(grafana["admin"]["existingSecret"], "observability-grafana-admin")
                        if mode == "none":
                            seed.assert_not_called()
                            self.assertNotIn("postgresql-baseline", children)
                            self.assertTrue(provision.call_args.args[1][1].endswith("/dev-no-database"))
                        else:
                            seed.assert_called_once()
                        dns.assert_called_once()
                        verify.assert_called_once()
                    else:
                        self.assertEqual(result, 1)
                        self.assertIn("Deploy blocked by deletion", errors.getvalue())
                        prepare.assert_not_called()
                        gitops.assert_not_called()
                        seed.assert_not_called()
                        self.assertEqual((folder / "prior.json").read_text(), "preserve checkpoint")
