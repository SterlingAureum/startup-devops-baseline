import argparse
from contextlib import nullcontext
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/delivery"))
import common
import flow
import offline
import promotion_check
import runtime
import verification


CFG = common.config()


def fixture():
    labels = {"app": "another-http-app", "instance": "example"}
    return [
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "another-http-app"},
         "spec": {"selector": {"matchLabels": labels.copy()}, "template": {
             "metadata": {"labels": labels.copy(), "annotations": {"platform.startup.dev/environment": "aws-dev"}},
             "spec": {"containers": [{"name": "server", "image": "example.invalid/another/app@sha256:" + "a" * 64,
                                      "ports": [{"name": "http", "containerPort": 8080}],
                                      "readinessProbe": {"httpGet": {"path": "/ready", "port": "http"}}}]}}}},
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "another-http-app", "labels": labels.copy()},
         "spec": {"selector": labels.copy(), "ports": [{"name": "web", "port": 80, "targetPort": "http"}]}},
        {"apiVersion": "monitoring.coreos.com/v1", "kind": "ServiceMonitor", "metadata": {"name": "another-http-app"},
         "spec": {"selector": {"matchLabels": labels.copy()}, "endpoints": [{"port": "web", "path": "/metrics"}]}}
    ]


class RoutingTests(unittest.TestCase):
    def test_docs_do_not_trigger_cloud_or_application_work(self):
        result = flow.classify(["README.md", "docs/guide.md"], CFG)
        self.assertFalse(any(result[key] for key in ("application", "iac", "platform", "render", "runtime_dev")))

    def test_archived_scripts_do_not_reenter_current_checks(self):
        result = flow.classify(["archive/v0.12/scripts/validate-ci-quality-gates.sh"], CFG)
        self.assertFalse(any(result[key] for key in ("application", "tests", "iac", "platform", "render", "runtime_dev")))

    def test_local_tools_and_unknown_code_run_current_checks(self):
        for path in ("scripts/ops/local.py", "new-tool/entry.py"):
            with self.subTest(path=path):
                result = flow.classify([path], CFG)
                self.assertTrue(result["tests"] and result["iac"] and result["platform"] and result["render"])
                self.assertFalse(result["application"])

    def test_source_runs_tests_and_render_but_not_iac_or_runtime(self):
        result = flow.classify(["apps/demo-api/src/main.py"], CFG)
        self.assertTrue(result["application"] and result["tests"] and result["render"])
        self.assertFalse(result["iac"] or result["runtime_dev"])

    def test_mixed_change_combines_checks(self):
        result = flow.classify(["infra/terraform/aws/main.tf", "apps/demo-api/src/main.py"], CFG)
        self.assertTrue(result["application"] and result["iac"])

    def test_release_change_targets_one_environment_without_rebuild(self):
        result = flow.classify([CFG["environments"]["aws-test"]["release"]], CFG)
        self.assertEqual(result["environments"], ["aws-test"])
        self.assertTrue(result["runtime_test"])
        self.assertFalse(result["runtime_dev"] or result["application"])

    def test_shared_chart_rechecks_environments(self):
        result = flow.classify(["apps/demo-api/helm/templates/service.yaml"], CFG)
        self.assertEqual(set(result["environments"]), set(CFG["environments"]))
        self.assertTrue(result["runtime_dev"] and result["runtime_test"])
        self.assertTrue(result["runtime_prod"])

    def test_similarly_named_path_is_not_application_code(self):
        self.assertFalse(flow.classify(["apps/demo-api/src-backup/main.py"], CFG)["application"])

    def test_repository_path_mapping_is_configurable(self):
        cfg = deepcopy(CFG)
        cfg["paths"]["application"] = ["src/", "Dockerfile"]
        self.assertTrue(flow.classify(["src/service.java"], cfg)["application"])
        self.assertFalse(flow.classify(["apps/demo-api/src/main.py"], cfg)["application"])

    def test_gate_changes_recheck_shared_contracts(self):
        result = flow.classify(["scripts/delivery/runtime.py"], CFG)
        self.assertTrue(result["tests"] and result["render"] and result["iac"] and result["platform"])


class OfflineTests(unittest.TestCase):
    def check(self, value):
        return offline.validate(value, "aws-dev", "startup-apps")

    def test_other_app_passes_without_demo_metric_names(self):
        self.check(fixture())

    def test_rejects_known_previous_prototype_gaps(self):
        for mutation in ("probe", "selector", "numeric-port", "init-image"):
            with self.subTest(mutation=mutation):
                objects = fixture()
                workload = objects[0]
                container = workload["spec"]["template"]["spec"]["containers"][0]
                if mutation == "probe":
                    container["readinessProbe"] = {"unsupportedProbeField": True}
                elif mutation == "selector":
                    workload["spec"]["selector"]["matchLabels"] = {"app": "wrong"}
                elif mutation == "numeric-port":
                    objects[1]["spec"]["ports"][0]["targetPort"] = 9999
                else:
                    workload["spec"]["template"]["spec"]["initContainers"] = [{"name": "init", "image": "example.invalid/app:latest"}]
                with self.assertRaises(common.Rejected):
                    self.check(objects)

    def test_wrong_environment_and_namespace_rejected(self):
        for key, value in (("environment", "aws-test"), ("namespace", "wrong")):
            kwargs = {"environment": "aws-dev", "namespace": "startup-apps"}
            kwargs[key] = value
            objects = fixture()
            for item in objects:
                item["metadata"]["namespace"] = "startup-apps"
            with self.assertRaises(common.Rejected):
                offline.validate(objects, **kwargs)

    def test_monitor_wiring_must_select_app_and_service_port(self):
        for change in ("selector", "port", "namespace"):
            objects = fixture()
            spec = objects[2]["spec"]
            if change == "selector":
                spec["selector"]["matchLabels"] = {"app": "wrong"}
            elif change == "port":
                spec["endpoints"][0]["port"] = "wrong"
            else:
                spec["namespaceSelector"] = {"any": True}
            with self.subTest(change=change), self.assertRaises(common.Rejected):
                self.check(objects)

    def test_missing_metrics_requires_explicit_optional_profile(self):
        objects = fixture()[:2]
        with self.assertRaises(common.Rejected):
            self.check(objects)
        offline.validate(objects, "aws-dev", "startup-apps", metrics_required=False)

    def test_local_can_use_loaded_tag(self):
        objects = fixture()
        objects[0]["spec"]["template"]["metadata"]["annotations"]["platform.startup.dev/environment"] = "local"
        objects[0]["spec"]["template"]["spec"]["containers"][0]["image"] = "local-app:dev"
        offline.validate(objects, "local", "startup-apps")

    def test_duplicate_yaml_is_rejected(self):
        with self.assertRaises(common.Rejected):
            yaml.load("image: first\nimage: second\n", Loader=common.UniqueLoader)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.value = common.release(common.repo_path(CFG["environments"]["aws-dev"]["release"]))
        self.app = {"status": {"sync": {"status": "Synced", "revision": "c" * 40}, "health": {"status": "Healthy"}}}
        self.workload = fixture()[0]
        self.workload["metadata"]["generation"] = 2
        self.workload["spec"]["replicas"] = 1
        self.workload["status"] = {"observedGeneration": 2, "updatedReplicas": 1, "readyReplicas": 1}
        template = self.workload["spec"]["template"]
        template["metadata"]["annotations"]["platform.startup.dev/source-commit"] = self.value["delivery"]["sourceCommit"]
        image = self.value["image"]["repository"] + "@" + self.value["image"]["digest"]
        template["spec"]["containers"][0]["image"] = image
        self.pods = {"items": [{"metadata": {}, "spec": deepcopy(template["spec"]), "status": {
            "containerStatuses": [{"name": "server", "ready": True, "imageID": image}]}}]}

    def check(self):
        runtime.verify_cluster(self.app, self.workload, self.pods, self.value, "aws-dev", "c" * 40, "server")

    def test_exact_current_deployment_passes(self):
        self.check()

    def test_runtime_report_from_observations_is_accepted(self):
        cfg = deepcopy(CFG)
        cfg["application"]["container"] = "server"
        self.workload["metadata"]["uid"] = "sample-uid"
        self.app["status"]["resources"] = [{"kind": "Deployment", "namespace": cfg["application"]["namespace"],
                                            "name": "sample"}]
        http = {"environment": "aws-dev", "version": self.value["release"]["applicationVersion"]}
        metrics = {"status": "success", "data": {"resultType": "vector", "result": [{"value": [1, "1"]}]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verified.json"
            args = ["runtime", "--environment", "aws-dev", "--revision", "c" * 40, "--output", str(path)]
            with patch.object(sys, "argv", args), patch.object(runtime, "config", return_value=cfg), \
                    patch.object(runtime, "run", return_value=subprocess.CompletedProcess([], 0, stdout="c" * 40)), \
                    patch.object(runtime, "prometheus_endpoint", return_value=nullcontext("http://localhost")), \
                    patch.object(runtime, "kubectl", side_effect=[self.app, self.workload, self.pods]), \
                    patch.object(runtime, "fetch_json", side_effect=[http, metrics]):
                self.assertEqual(runtime.main(), 0)
            report = json.loads(path.read_text())
        verification.require_pass(report, cfg["application"]["release_name"], "aws-dev")
        self.assertEqual(report["analysis"]["status"], "not_applicable")
        self.assertEqual(report["observed"]["workload_uid"], "sample-uid")

    def test_old_argocd_revision_is_not_acceptance(self):
        self.app["status"]["sync"]["revision"] = "d" * 40
        with self.assertRaises(common.Rejected):
            self.check()

    def test_old_or_unready_pod_prevents_promotion(self):
        self.pods["items"][0]["status"]["containerStatuses"][0]["imageID"] = "sha256:" + "0" * 64
        with self.assertRaises(common.Rejected):
            self.check()

    def test_manual_canary_pause_is_not_success(self):
        self.workload["kind"] = "Rollout"
        self.workload["status"].update(phase="Paused", currentPodHash="abc", stableRS="old", pauseConditions=[{}])
        with self.assertRaises(common.Rejected):
            self.check()

    def test_http_identity_must_match_target(self):
        with self.assertRaises(common.Rejected):
            runtime.verify_http({"environment": "aws-test", "version": "v1"}, "aws-dev", "v1")

    def test_empty_or_nan_metrics_cannot_pass(self):
        for values in ([], ["NaN"], ["0"]):
            payload = {"status": "success", "data": {"resultType": "vector", "result": [{"value": [1, value]} for value in values]}}
            with self.subTest(values=values), self.assertRaises(common.Rejected):
                runtime.verify_metrics(payload)
        runtime.verify_metrics({"status": "success", "data": {"resultType": "vector", "result": [{"value": [1, "2"]}]}})


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        for module in (common, flow, runtime):
            item = patch.object(module, "ROOT", self.root)
            item.start()
            self.addCleanup(item.stop)
        self.cfg = deepcopy(CFG)
        self.value = {"image": {"repository": "example.invalid/team/app", "tag": "sha-aaaaaaa", "digest": "sha256:" + "a" * 64},
                      "release": {"applicationVersion": "sha-aaaaaaa"},
                      "delivery": {"sourceRepository": "team/app", "sourceCommit": "a" * 40, "workflowRunId": "100"}}
        for name in ("aws-dev", "aws-test", "aws-prod"):
            value = deepcopy(self.value)
            if name != "aws-dev":
                value["image"]["digest"] = "sha256:" + "b" * 64
            path = common.repo_path(self.cfg["environments"][name]["release"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(value))
        cfg_path = self.root / "delivery/standard/config.json"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(json.dumps(self.cfg))
        for env in self.cfg["environments"].values():
            for item in env["values"]:
                path = common.repo_path(item)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("env: example\n")
        self.report = {"verified": True, "environment": "aws-dev", "release": deepcopy(self.value),
                       "release_sha256": common.fingerprint(common.repo_path(self.cfg["environments"]["aws-dev"]["release"])),
                       "inputs_sha256": flow.input_fingerprint(self.cfg, "aws-dev"),
                       "run_id": "123", "run_attempt": "1", "config_revision": "c" * 40}

        self.report.update(schema_version=1, result="passed", application_id=self.cfg["application"]["release_name"],
                           repository="team/app", producer_job="verify (aws-dev)",
                           observed={"gitops_revision": "c" * 40, "image": "example.invalid/team/app@sha256:" + "a" * 64,
                                     "pod_image_ids": ["runtime@sha256:" + "a" * 64],
                                     "source_commit": "a" * 40})

    def test_promotion_copies_same_digest_and_preserves_target_settings(self):
        target = common.repo_path(self.cfg["environments"]["aws-test"]["release"])
        value = common.load_yaml(target)
        value["customTargetSetting"] = "preserved"
        target.write_text(yaml.safe_dump(value))
        flow.prepare_release(self.cfg, "aws-test", self.report)
        actual = common.release(target)
        self.assertEqual(common.identity(actual), self.value)
        self.assertEqual(actual["customTargetSetting"], "preserved")
        self.assertEqual(actual["promotion"]["sourceEnvironment"], "aws-dev")

    def test_failed_skipped_or_wrong_source_verification_rejected(self):
        for field, value in (("verified", False), ("environment", "aws-test")):
            report = deepcopy(self.report)
            report[field] = value
            with self.subTest(field=field), self.assertRaises(common.Rejected):
                flow.prepare_release(self.cfg, "aws-test", report)

    def test_stale_source_release_or_input_rejected(self):
        for field in ("release_sha256", "inputs_sha256"):
            report = deepcopy(self.report)
            report[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(common.Rejected):
                flow.prepare_release(self.cfg, "aws-test", report)

    def test_rejects_wrong_app_observation_and_legacy_evidence(self):
        for key, value in (("schema_version", 0), ("result", "failed"), ("application_id", "other"),
                           ("observed", dict(self.report["observed"], pod_image_ids=[])),
                           ("observed", dict(self.report["observed"], gitops_revision="f" * 40))):
            with self.subTest(key=key), self.assertRaises(common.Rejected):
                flow.prepare_release(self.cfg, "aws-test", dict(self.report, **{key: value}))

    def test_runtime_writes_failed_diagnostic_and_exits_nonzero(self):
        path = self.root / "verified.json"
        path.write_text(json.dumps(self.report))
        args = ["runtime", "--environment", "aws-dev", "--revision", "c" * 40, "--output", str(path)]
        with patch.object(sys, "argv", args), patch.object(runtime, "config", return_value=self.cfg), \
                patch.object(runtime, "run", return_value=subprocess.CompletedProcess([], 0, stdout="d" * 40)):
            self.assertEqual(runtime.main(), 1)
        diagnostic = json.loads(path.read_text())
        self.assertFalse(diagnostic["verified"])
        self.assertEqual(diagnostic["result"], "failed")
        self.assertIn("checkout", diagnostic["reason"])
        self.assertNotIn("checks", diagnostic)

    def test_analysis_references_belong_to_the_observed_rollout(self):
        observed = dict(workload_kind="Rollout", workload_uid="demo-uid", namespace="apps", pod_hash="hash")
        runs = [{"metadata": {"ownerReferences": [{"uid": uid}], "name": uid, "uid": uid},
                 "status": {"phase": "Successful"}} for uid in ("another-uid", "demo-uid")]
        with patch.object(runtime, "kubectl", return_value={"items": runs}) as read:
            result = runtime.analysis_references(observed)
        read.assert_called_once_with("-n", "apps", "get", "analysisruns", "-l", "rollouts-pod-template-hash=hash")
        self.assertEqual([r["name"] for r in result["recent"]], ["demo-uid"])

    def test_production_is_opt_in(self):
        report = deepcopy(self.report)
        report["environment"] = "aws-test"
        with patch.dict(os.environ, {"DELIVERY_PROD_ENABLED": "false"}), self.assertRaises(common.Rejected):
            flow.prepare_release(self.cfg, "aws-prod", report)

    def test_verification_report_must_bind_release_and_deployment_inputs(self):
        promotion_check.validate_report(self.report, self.cfg, "aws-dev", self.value, "123", "1")
        changed = deepcopy(self.value)
        changed["image"]["digest"] = "sha256:" + "d" * 64
        with self.assertRaises(common.Rejected):
            promotion_check.validate_report(self.report, self.cfg, "aws-dev", changed, "123", "1")

    def test_local_git_pr_changes_only_target_without_rebuild_or_merge(self):
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()
        origin = Path(self.temp.name) / "origin.git"
        git("init", "-b", "main")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        git("add", ".")
        git("commit", "-m", "baseline")
        git("clone", "--bare", str(self.root), str(origin))
        git("remote", "add", "origin", str(origin))
        candidate = Path(self.temp.name) / "verified.json"
        candidate.write_text(json.dumps(self.report))
        args = argparse.Namespace(target="aws-test", candidate=str(candidate), image=None, commit=None)
        env = {"GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": "team/app", "GITHUB_RUN_ID": "123",
               "GITHUB_RUN_ATTEMPT": "1", "DELIVERY_PR_TOKEN": "test-only"}
        created = []
        pages = [[]]

        def github(args, **kwargs):
            if args[:2] == ["gh", "api"]:
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(pages))
            self.assertEqual(args[:3], ["gh", "pr", "create"])
            branch = args[args.index("--head") + 1]
            created.append(branch)
            if len(created) == 1:
                raise subprocess.CalledProcessError(1, args)
            git("push", "origin", "HEAD:refs/pull/21/head")
            pages[0].append({"head": {"repo": {"full_name": "team/app"}, "ref": branch},
                             "number": 21, "html_url": "https://example.invalid/pr/21"})
            return subprocess.CompletedProcess(args, 0, stdout="https://example.invalid/pr/21")

        with patch.dict(os.environ, env), patch.object(flow, "config", return_value=self.cfg), \
                patch.object(flow, "render_environment", return_value=""), patch.object(flow, "run", side_effect=github):
            with self.assertRaises(subprocess.CalledProcessError):
                flow.create_pr(args, self.cfg)
            with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
                flow.create_pr(args, self.cfg)
            self.assertEqual(created[0], created[1])
            self.assertEqual(git("diff", "--name-only", "main", "HEAD"), self.cfg["environments"]["aws-test"]["release"])
            self.assertEqual(git("rev-parse", "main"), git("rev-parse", "HEAD^"))
            with patch.object(flow, "verified_report", return_value=self.report) as inspect:
                flow.create_pr(args, self.cfg)
            inspect.assert_called_once_with("team/app", "123", "1", "aws-dev")
            self.assertEqual(len(created), 2)
            with patch.object(flow, "verified_report", side_effect=common.Rejected("expired")), \
                    self.assertRaisesRegex(common.Rejected, "stale PR"):
                flow.create_pr(args, self.cfg)
            self.assertEqual(len(created), 2)


class ReportProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {"id": 123, "status": "in_progress", "conclusion": None, "head_branch": "main",
                         "run_attempt": 1, "head_repository": {"full_name": "team/app"}, "event": "push",
                         "head_sha": "c" * 40, "path": ".github/workflows/delivery-runtime.yaml"}
        self.job = {"name": "verify-dev / verify (aws-dev)", "head_sha": "c" * 40,
                    "conclusion": "success", "run_attempt": 1}
        self.report = {"config_revision": "c" * 40, "repository": "team/app", "environment": "aws-dev",
                       "run_id": "123", "run_attempt": "1", "producer_job": "verify (aws-dev)"}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zipped:
            zipped.writestr("verified.json", json.dumps(self.report))
        self.archive = buf.getvalue()
        self.artifact = {"id": 5, "name": "delivery-verified-aws-dev-123-1", "expired": False,
                         "size_in_bytes": len(self.archive)}

    def read(self):
        responses = [self.workflow, {"jobs": [self.job]}, {"artifacts": [self.artifact]}, self.archive]
        with patch.object(verification, "api", side_effect=responses) as remote:
            report = verification.verified_report("team/app", "123", "1", "aws-dev")
        self.assertIn("attempts/1/jobs?", remote.call_args_list[1].args[0])
        return report

    def test_source_succeeds_independently_of_other_environment(self):
        for status, conclusion in [("in_progress", None), ("completed", "failure")]:
            self.workflow.update(status=status, conclusion=conclusion)
            self.assertEqual(self.read(), self.report)
        self.workflow.update(path=".github/workflows/delivery-promote.yaml", event="workflow_dispatch")
        self.job["name"] = "verify-source / verify (aws-dev)"
        self.assertEqual(self.read(), self.report)

    def test_rejects_failed_or_wrong_job(self):
        for key, value in (("conclusion", "failure"), ("run_attempt", 2), ("name", "verify-test / verify (aws-test)"),
                           ("head_sha", "f" * 40)):
            with self.subTest(key=key), patch.dict(self.job, {key: value}), self.assertRaises(common.Rejected):
                self.read()

    def test_rejects_foreign_or_pr_workflow(self):
        for key, value in (("event", "pull_request"), ("head_branch", "feature"), ("run_attempt", 2),
                           ("head_repository", {"full_name": "other/app"}),
                           ("path", ".github/workflows/delivery-report-rehearsal.yaml")):
            with self.subTest(key=key), patch.dict(self.workflow, {key: value}), self.assertRaises(common.Rejected):
                self.read()

    def test_expired_or_wrong_artifact(self):
        for key, value in (("expired", True), ("name", "delivery-diagnostic-aws-dev-123-1")):
            with self.subTest(key=key), patch.dict(self.artifact, {key: value}), self.assertRaises(common.Rejected):
                self.read()


if __name__ == "__main__":
    unittest.main()
