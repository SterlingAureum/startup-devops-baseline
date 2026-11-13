from copy import deepcopy
from contextlib import nullcontext, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("local_ops", ROOT / "scripts/examples/demo_api.py")
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)
COMMIT = "a" * 40
STABLE_HASH = "stable-demo"


def args(command, *extra):
    return local.parser().parse_args([command, *extra])


def fixture():
    apps = [{"status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}]
    workload = {"metadata": {"generation": 3}, "spec": {"replicas": 1},
                "status": {"observedGeneration": 3, "phase": "Healthy", "readyReplicas": 1, "updatedReplicas": 1,
                           "currentPodHash": STABLE_HASH, "stableRS": STABLE_HASH}}
    pods = {"items": [{"metadata": {"annotations": {"platform.startup.dev/source-commit": COMMIT}},
                       "spec": {"containers": [{"name": "demo-api", "image": local.image_for(COMMIT)}]},
                       "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                                  "containerStatuses": [{"name": "demo-api", "ready": True, "imageID": "containerd://example"}]}}]}
    return apps, workload, pods


class LocalBoundaryTests(unittest.TestCase):
    def test_dry_run_invokes_no_tools(self):
        with patch.object(local, "run") as run, patch.object(local.shutil, "which") as which, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(local.main(["up", "--revision", "feature/local", "--dry-run"]), 0)
            self.assertFalse(json.loads(output.getvalue())["executed"])
            run.assert_not_called()
            which.assert_not_called()

    def test_invalid_targets_and_confirmation_stop_before_tools(self):
        for argv in (["destroy"], ["destroy", "--confirm", "aws-dev"], ["create", "--cluster", "../prod"],
                     ["up"], ["up", "--revision", "--bad"], ["create", "--repo-url", "https://user:token@example.invalid/repo.git"]):
            with self.subTest(argv=argv), patch.object(local, "run") as run, redirect_stderr(io.StringIO()):
                try:
                    result = local.main(argv)
                except SystemExit as error:
                    result = error.code
                self.assertNotEqual(result, 0)
                run.assert_not_called()




    def test_source_mismatch_stops_up_before_cluster_creation(self):
        with patch.object(local.shutil, "which", return_value="/fake/tool"), patch.object(local, "source_commit", side_effect=local.LocalError("mismatch")), patch.object(local.Driver, "create") as create, redirect_stderr(io.StringIO()):
            self.assertEqual(local.main(["up", "--revision", "feature/local"]), 1)
            create.assert_not_called()

    def test_annotated_tag_is_resolved_to_its_commit_with_real_local_git(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "source"
            checkout = Path(directory) / "checkout"
            remote.mkdir()
            subprocess.run(["git", "init", "-q", str(remote)], check=True)
            for name in ("clusters/local/platform/Chart.yaml", "apps/demo-api/helm/Chart.yaml", "scripts/ops/local.py"):
                file = remote / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("source fixture\n")
            subprocess.run(["git", "add", "."], cwd=remote, check=True)
            identity = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]
            subprocess.run([*identity, "commit", "-qm", "fixture"], cwd=remote, check=True)
            subprocess.run([*identity, "tag", "-a", "local-test", "-m", "annotated source tag"], cwd=remote, check=True)
            subprocess.run(["git", "clone", "-q", str(remote), str(checkout)], check=True)
            expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
            def actual_git(command, *, cwd=checkout, **kwargs):
                return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=True)
            value = args("deploy", "--revision", "local-test")
            value.repo_url = str(remote)
            with patch.object(local, "run", side_effect=actual_git):
                self.assertEqual(local.source_commit(value), expected)
                # A fixed local verifier can inspect an older deployed source
                # without rebuilding it or rendering a dirty verifier checkout.
                (checkout / "scripts/ops/local.py").write_text("uncommitted verifier fix\n")
                with local.verification_source(value) as (commit, source_root):
                    self.assertEqual(commit, expected)
                    self.assertEqual((source_root / "scripts/ops/local.py").read_text(), "source fixture\n")
                self.assertFalse(source_root.exists())

    def test_verify_resumes_deployed_revision_without_build_or_checkout_equality(self):
        source_root = Path("/fixture/deployed-source")
        with patch.object(local.shutil, "which", return_value="/fake/tool"), patch.object(local, "Driver") as driver_class, patch.object(local, "clean_commit") as clean, patch.object(local, "verification_source", return_value=nullcontext((COMMIT, source_root))) as source:
            driver = driver_class.return_value
            driver.deployed_revision.return_value = COMMIT
            self.assertEqual(local.main(["verify", "--cluster", "existing-local"]), 0)
            self.assertEqual(source.call_args.args[0].revision, COMMIT)
            driver.verify.assert_called_once_with(COMMIT, source_root=source_root)
            clean.assert_not_called()
            for method in ("create", "install", "build", "deploy", "destroy"):
                getattr(driver, method).assert_not_called()

    def test_deployed_revision_requires_matching_repo_and_fixed_commit(self):
        value = args("verify")
        local.validate_options(value)
        driver = local.Driver(value)
        root = {"spec": {"source": {"repoURL": value.repo_url, "targetRevision": COMMIT}}}
        with patch.object(driver, "kubernetes", return_value=nullcontext()), patch.object(driver, "kube", return_value=subprocess.CompletedProcess([], 0, json.dumps(root), "")):
            self.assertEqual(driver.deployed_revision(), COMMIT)
        for field, bad in (("targetRevision", "main"), ("repoURL", "https://example.invalid/another/repo.git")):
            other = deepcopy(root)
            other["spec"]["source"][field] = bad
            with self.subTest(field=field), patch.object(driver, "kubernetes", return_value=nullcontext()), patch.object(driver, "kube", return_value=subprocess.CompletedProcess([], 0, json.dumps(other), "")):
                with self.assertRaises(local.LocalError):
                    driver.deployed_revision()

    def test_dirty_source_is_not_built(self):
        with patch.object(local, "run", return_value=subprocess.CompletedProcess([], 0, " M apps/demo-api/src/main.py\n", "")):
            with self.assertRaises(local.LocalError):
                local.clean_commit()

    def test_local_root_pins_parent_and_children_to_same_commit(self):
        value = args("deploy", "--revision", "feature/local")
        root = local.root_application(value, COMMIT)
        self.assertEqual(root["spec"]["source"]["targetRevision"], COMMIT)
        parameters = {item["name"]: item["value"] for item in root["spec"]["source"]["helm"]["parameters"]}
        self.assertEqual(parameters["git.targetRevision"], COMMIT)
        self.assertEqual(parameters["demoApi.localImage.sourceCommit"], COMMIT)
        self.assertEqual(parameters["demoApi.rehearsalFault.mode"], "disabled")

    def test_existing_image_with_different_source_is_rejected(self):
        driver = local.Driver(args("build"))
        with patch.object(driver, "clusters", return_value=[driver.args.cluster]), patch.object(driver, "image_label", return_value=subprocess.CompletedProcess([], 0, "b" * 40, "")), patch.object(local, "run") as run:
            with self.assertRaises(local.LocalError):
                driver.build(COMMIT)
            run.assert_not_called()

    @unittest.skipUnless(shutil.which("helm"), "Helm is required for actual local chart rendering")
    def test_rendered_local_image_clears_cloud_digest_and_sets_source(self):
        value = args("deploy", "--revision", "feature/local")
        command = ["helm", "template", "local-platform", "clusters/local/platform"]
        for name, item in local.local_parameters(value, COMMIT).items():
            command += ["--set" if name.endswith(".enabled") else "--set-string", name + "=" + item]
        output = subprocess.check_output(command, cwd=ROOT, text=True)
        child = next(item for item in yaml.safe_load_all(output) if item and item.get("metadata", {}).get("name") == "demo-api")
        command = ["helm", "template", "demo-api", "apps/demo-api/helm", "--namespace", "startup-apps"]
        for item in child["spec"]["source"]["helm"]["parameters"]:
            command += ["--set-string", item["name"] + "=" + item["value"]]
        rendered = list(yaml.safe_load_all(subprocess.check_output(command, cwd=ROOT, text=True)))
        workload = next(item for item in rendered if item and item.get("kind") == "Rollout")
        self.assertEqual(workload["spec"]["template"]["spec"]["containers"][0]["image"], local.image_for(COMMIT))
        self.assertEqual(workload["spec"]["template"]["metadata"]["annotations"]["platform.startup.dev/source-commit"], COMMIT)


def verify_state(apps, workload, pods, commit):
    local.wait_for_applications(apps)
    _, desired = local.converged_rollout(workload)
    local.verify_pod_identity(local.ready_demo_pods(pods, desired), commit)


class LocalVerificationTests(unittest.TestCase):
    def test_current_ready_state_passes(self):
        verify_state(*fixture(), COMMIT)

    def test_string_observed_generation_from_reported_failure_passes(self):
        apps, workload, pods = fixture()
        workload["status"]["observedGeneration"] = "3"
        verify_state(apps, workload, pods, COMMIT)

    def test_all_workload_counters_can_be_decimal_strings(self):
        apps, workload, pods = fixture()
        workload["metadata"]["generation"] = "3"
        workload["spec"]["replicas"] = "1"
        for field in ("observedGeneration", "readyReplicas", "updatedReplicas"):
            workload["status"][field] = str(workload["status"][field])
        verify_state(apps, workload, pods, COMMIT)

    def test_stale_or_missing_status_still_rejected_after_conversion(self):
        for field, value in (("observedGeneration", "2"), ("readyReplicas", "0"), ("updatedReplicas", "0")):
            apps, workload, pods = fixture()
            workload["status"][field] = value
            with self.subTest(field=field), self.assertRaises(local.LocalError):
                verify_state(apps, workload, pods, COMMIT)
            del workload["status"][field]
            with self.subTest(missing=field), self.assertRaises(local.LocalError):
                verify_state(apps, workload, pods, COMMIT)

    def test_invalid_counter_types_fail_with_clear_error(self):
        for section, field in (("metadata", "generation"), ("spec", "replicas"), ("status", "observedGeneration"), ("status", "readyReplicas"), ("status", "updatedReplicas")):
            for value in (None, True, False, -1, 1.5, "-1", "1.5", "", "unknown", {}, []):
                apps, workload, pods = fixture()
                workload[section][field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(local.LocalError, section + r"\." + field):
                    verify_state(apps, workload, pods, COMMIT)

    def test_paused_rollout_and_stale_generation_are_rejected(self):
        for key, value in (("phase", "Paused"), ("observedGeneration", 1), ("readyReplicas", 0), ("updatedReplicas", 0)):
            apps, workload, pods = fixture()
            workload["status"][key] = value
            with self.subTest(key=key), self.assertRaises(local.LocalError):
                verify_state(apps, workload, pods, COMMIT)

    def test_unhealthy_platform_and_stale_pods_are_rejected(self):
        for mutation in ("platform", "image", "source", "ready", "empty"):
            apps, workload, pods = fixture()
            pod = pods["items"][0]
            if mutation == "platform": apps[0]["status"]["health"]["status"] = "Progressing"
            elif mutation == "image": pod["spec"]["containers"][0]["image"] = "other:latest"
            elif mutation == "source": pod["metadata"]["annotations"]["platform.startup.dev/source-commit"] = "b" * 40
            elif mutation == "ready": pod["status"]["containerStatuses"][0]["ready"] = False
            else: pods["items"] = []
            with self.subTest(mutation=mutation), self.assertRaises(local.LocalError):
                verify_state(apps, workload, pods, COMMIT)


class LocalVerificationFlowTests(unittest.TestCase):
    def exercise_verify(self, *, mismatch=None, updating=None):
        driver = local.Driver(args("verify"))
        apps, workload, pods = fixture()
        source = {"repoURL": driver.args.repo_url, "targetRevision": COMMIT}
        child = {"kind": "Application", "metadata": {"name": "demo-api"}, "spec": {"source": source}}
        app = deepcopy(apps[0])
        app["spec"] = {"source": source}
        app["status"]["sync"]["revision"] = COMMIT
        workload["spec"]["selector"] = {"matchLabels": {"app": "demo-api"}}
        pod = pods["items"][0]
        pod["metadata"]["name"] = "stable-pod"
        if mismatch == "source":
            pod["metadata"]["annotations"]["platform.startup.dev/source-commit"] = "b" * 40
        elif mismatch == "image":
            pod["spec"]["containers"][0]["image"] = "registry.example/demo:published"
        old_pod = deepcopy(pod)
        old_pod["metadata"]["annotations"]["platform.startup.dev/source-commit"] = "c" * 40
        calls = []

        def kube(*command):
            calls.append(command)
            if "application" in command:
                body = deepcopy(app)
                if updating == "root" and len(calls) == 1:
                    body["status"]["operationState"] = {"phase": "Running"}
            elif "rollout" in command:
                body = deepcopy(workload)
                if updating == "rollout" and sum("rollout" in call for call in calls) == 1:
                    body["status"]["currentPodHash"] = "candidate"
            elif "pods" in command:
                selector = command[command.index("-l") + 1]
                body = pods if f"rollouts-pod-template-hash={STABLE_HASH}" in selector else {"items": [pod, old_pod]}
            else:
                endpoint = command[-1].rsplit("/", 1)[-1]
                if endpoint == "metrics":
                    return subprocess.CompletedProcess([], 0, 'demo_api_http_requests_total{route="/ready"} 1', "")
                body = {"health": {"status": "ok"}, "ready": {"status": "ready"},
                        "version": {"environment": "local", "version": f"local-{COMMIT[:12]}"}}[endpoint]
                if endpoint == "version" and mismatch == "http":
                    body["version"] = "registry-release"
            return subprocess.CompletedProcess([], 0, json.dumps(body), "")

        rendered = subprocess.CompletedProcess([], 0, yaml.safe_dump(child), "")
        with patch.object(local, "run", return_value=rendered), patch.object(driver, "kubernetes", return_value=nullcontext()), patch.object(driver, "kube", side_effect=kube), patch.object(local.time, "sleep") as sleep, redirect_stdout(io.StringIO()):
            if mismatch:
                message = "does not match the local build" if mismatch in ("source", "image") else "HTTP version"
                with self.assertRaisesRegex(local.LocalError, message):
                    driver.verify(COMMIT)
                sleep.assert_not_called()
            else:
                driver.verify(COMMIT)
                self.assertEqual(sleep.call_count, int(bool(updating)))
        pod_reads = [command for command in calls if "pods" in command]
        self.assertEqual(len(pod_reads), 1)
        self.assertIn(f"rollouts-pod-template-hash={STABLE_HASH}", pod_reads[0][pod_reads[0].index("-l") + 1])
        if mismatch in ("source", "image"):
            self.assertFalse(any("--raw" in command for command in calls))

    def test_waits_for_active_root_operation_then_checks_only_stable_pods(self):
        for updating in ("root", "rollout"):
            with self.subTest(updating=updating):
                self.exercise_verify(updating=updating)

    def test_stable_identity_or_http_mismatch_does_not_retry(self):
        for mismatch in ("source", "image", "http"):
            with self.subTest(mismatch=mismatch):
                self.exercise_verify(mismatch=mismatch)

    def test_convergence_timeout_does_not_query_pods(self):
        driver = local.Driver(args("verify", "--timeout", "1"))
        child = {"kind": "Application"}
        root = {"status": {"sync": {"revision": "b" * 40}}}
        rendered = subprocess.CompletedProcess([], 0, yaml.safe_dump(child), "")
        observed = subprocess.CompletedProcess([], 0, json.dumps(root), "")
        with patch.object(local, "run", return_value=rendered), patch.object(driver, "kubernetes", return_value=nullcontext()), patch.object(driver, "kube", return_value=observed) as kube, patch.object(local.time, "monotonic", side_effect=(0, 2)):
            with self.assertRaisesRegex(local.LocalError, "Local convergence timed out.*Root Application"):
                driver.verify(COMMIT)
            kube.assert_called_once()
