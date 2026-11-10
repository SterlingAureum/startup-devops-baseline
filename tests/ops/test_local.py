from contextlib import nullcontext, redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import cli
import configuration
import connections
import local

COMMIT = "a" * 40


def args(command="verify", *extra):
    value = cli.parser().parse_args([command, *extra])
    cli.configure(value)
    return value


def kubeconfig(cluster="startup-devops-baseline", server="https://127.0.0.1:12345"):
    name = "kind-" + cluster
    return {"apiVersion": "v1", "kind": "Config", "current-context": name,
            "clusters": [{"name": name, "cluster": {"server": server, "certificate-authority-data": "fixture-ca"}}],
            "users": [{"name": name, "user": {"client-certificate-data": "fixture-cert", "client-key-data": "fixture-key"}}],
            "contexts": [{"name": name, "context": {"cluster": name, "user": name}}]}


def application(name="custom-workload", commit=COMMIT):
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": name, "namespace": "argocd"},
            "spec": {"source": {"repoURL": "https://example.invalid/owner/config.git", "path": "apps/custom", "targetRevision": commit},
                     "destination": {"server": "https://kubernetes.default.svc", "namespace": "custom-apps"}},
            "status": {"sync": {"status": "Synced", "revision": commit}, "health": {"status": "Healthy"}}}


class ConfigurationTests(unittest.TestCase):
    def test_dry_run_and_show_do_not_run_tools_or_write_files(self):
        for command in (["show"], ["up", "--revision", "main", "--dry-run"], ["connect", "--dry-run"],
                        ["destroy", "--confirm", "startup-devops-baseline", "--dry-run"], ["show", "--env", "aws-dev"]):
            with self.subTest(command=command), patch.object(local, "run") as run, patch.object(cli.shutil, "which") as which, patch.object(connections, "atomic_write") as write, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(command), 0)
                self.assertFalse(json.loads(output.getvalue())["executed"])
                run.assert_not_called()
                which.assert_not_called()
                write.assert_not_called()

    def test_aws_is_inspection_only_even_for_dry_run(self):
        for command in ("up", "create", "destroy", "verify"):
            with self.subTest(command=command), patch.object(local, "run") as run, redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main([command, "--env", "aws-dev", "--dry-run"]), 1)
                run.assert_not_called()

    def test_invalid_targets_fail_before_tools(self):
        for extra in (["create", "--cluster", "../prod"], ["destroy"], ["up"], ["show", "--env", "missing"],
                      ["create", "--repo-url", "https://user:token@example.invalid/repo.git"],
                      ["create", "--timeout", "0"], ["status", "--kubeconfig-file", "/tmp/not-used"]):
            with self.subTest(extra=extra), patch.object(local, "run") as run, redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(extra), 1)
                run.assert_not_called()

    def test_reject_duplicate_fields_and_embedded_credentials(self):
        with self.assertRaises(configuration.OpsError):
            configuration.load_yaml("schema_version: 1\nschema_version: 2\n")
        env = configuration.environment(configuration.DEFAULT_CONFIG, "aws-dev")
        for key in ("access_key", "secret_key", "session_token"):
            other = deepcopy(env)
            other["aws"][key] = "should-not-be-accepted"
            with self.subTest(key=key), self.assertRaises(configuration.OpsError):
                configuration.validate_environment(other)

    def test_custom_inventory_selects_cluster_and_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environments.yaml"
            env = configuration.environment(configuration.DEFAULT_CONFIG, "local")
            env["kind"]["cluster"] = "my-local"
            env["gitops"]["repository"] = "https://example.invalid/team/gitops.git"
            path.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"workstation": env}}))
            value = args("status", "--config", str(path), "--env", "workstation", "--timeout", "20")
            self.assertEqual((value.cluster, value.repo_url, value.timeout), ("my-local", env["gitops"]["repository"], 20))


class ConnectionTests(unittest.TestCase):
    def test_merge_preserves_unrelated_data_and_adopts_identical_kind_entries(self):
        existing = kubeconfig("other")
        existing["preferences"] = {"colors": True}
        existing["extensions"] = [{"name": "other-tool", "extension": {"value": "retained"}}]
        incoming = kubeconfig()
        merged = connections.merge(existing, incoming, "startup-devops-baseline")
        self.assertEqual(merged["clusters"][0], existing["clusters"][0])
        self.assertEqual(merged["users"][0], existing["users"][0])
        self.assertEqual(merged["preferences"], existing["preferences"])
        self.assertEqual(merged["extensions"][0], existing["extensions"][0])
        self.assertEqual(merged["current-context"], incoming["current-context"])
        incoming["contexts"][0]["context"]["namespace"] = "my-namespace"
        adopted = connections.merge(incoming, kubeconfig(), "startup-devops-baseline")
        self.assertEqual(adopted["contexts"][0]["context"]["namespace"], "my-namespace")

    def test_owned_recreated_cluster_updates_but_foreign_collisions_fail(self):
        initial = connections.merge({}, kubeconfig(), "startup-devops-baseline")
        updated = connections.merge(initial, kubeconfig(server="https://127.0.0.1:54321"), "startup-devops-baseline")
        self.assertEqual(updated["clusters"][0]["cluster"]["server"], "https://127.0.0.1:54321")
        with self.assertRaises(configuration.OpsError):
            connections.merge(kubeconfig(server="https://foreign.invalid"), kubeconfig(), "startup-devops-baseline")
        initial["users"][0]["user"]["client-key-data"] = "manually-changed"
        with self.assertRaises(configuration.OpsError):
            connections.merge(initial, kubeconfig(), "startup-devops-baseline")

    def test_matching_names_and_certificates_do_not_adopt_extra_auth_or_proxy_settings(self):
        for section, field, extra in (("users", "user", {"exec": {"command": "unexpected-program", "apiVersion": "client.authentication.k8s.io/v1"}}),
                                      ("clusters", "cluster", {"proxy-url": "http://foreign.invalid"})):
            existing = kubeconfig()
            existing[section][0][field].update(extra)
            with self.subTest(section=section), self.assertRaises(configuration.OpsError):
                connections.merge(existing, kubeconfig(), "startup-devops-baseline")

    def test_connect_backup_permissions_and_conflict_does_not_modify_target(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            target = Path(directory) / "config"
            original = yaml.safe_dump(kubeconfig("other")).encode()
            target.write_bytes(original)
            connections.connect(kubeconfig(), "startup-devops-baseline", str(target))
            backups = list(target.parent.glob("config.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            for path in (target, backups[0]):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            foreign = yaml.safe_dump(kubeconfig(server="https://foreign.invalid"))
            target.write_text(foreign)
            with self.assertRaises(configuration.OpsError):
                connections.connect(kubeconfig(), "startup-devops-baseline", str(target))
            self.assertEqual(target.read_text(), foreign)

    def test_multiple_kubeconfigs_need_explicit_target(self):
        with patch.dict(os.environ, {"KUBECONFIG": "/a:/b"}):
            with self.assertRaises(configuration.OpsError):
                connections.target_path()
            self.assertEqual(connections.target_path("/chosen"), Path("/chosen"))

    def test_kind_output_cannot_introduce_other_named_entries(self):
        value = kubeconfig()
        value["contexts"].append(kubeconfig("foreign")["contexts"][0])
        with self.assertRaises(configuration.OpsError):
            connections.kind_config(yaml.safe_dump(value), "startup-devops-baseline")

    def test_persistent_debug_config_survives_failure_but_private_execution_config_is_removed(self):
        value = args()
        driver = local.Driver(value)
        commands = []
        def fake(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, yaml.safe_dump(kubeconfig()), "")
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)), patch.object(driver, "clusters", return_value=[value.cluster]), patch.object(local, "run", side_effect=fake), redirect_stdout(io.StringIO()):
            global_config = Path(home) / ".kube/config"
            global_config.parent.mkdir()
            global_config.write_text("user configuration remains unchanged")
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                with driver.kubernetes():
                    private = Path(driver.kubeconfig)
                    driver.kube("get", "nodes")
                    raise RuntimeError("fixture failure")
            self.assertFalse(private.exists())
            self.assertIsNone(driver.kubeconfig)
            saved = connections.private_path(value.cluster)
            self.assertTrue(saved.exists())
            self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
            self.assertEqual(global_config.read_text(), "user configuration remains unchanged")
        self.assertEqual(commands[-1][:3], ["kubectl", "--kubeconfig", str(private)])
        self.assertIn("kind-" + value.cluster, commands[-1])

    def test_absent_cluster_never_uses_workstation_context(self):
        driver = local.Driver(args())
        with patch.object(driver, "clusters", return_value=[]), patch.object(local, "run") as run:
            with self.assertRaises(configuration.OpsError), driver.kubernetes():
                pass
            run.assert_not_called()

    def test_destroy_is_named_and_does_not_touch_shared_config(self):
        value = args("destroy", "--cluster", "test-local", "--confirm", "test-local")
        driver = local.Driver(value)
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)), patch.object(driver, "clusters", return_value=["test-local", "other"]), patch.object(local, "run") as run, redirect_stdout(io.StringIO()):
            shared = Path(home) / ".kube/config"
            shared.parent.mkdir()
            shared.write_text("unchanged")
            connections.atomic_write(connections.private_path("test-local"), "dedicated")
            driver.destroy()
            self.assertEqual(run.call_args.args[0], ["kind", "delete", "cluster", "--name", "test-local"])
            self.assertEqual(shared.read_text(), "unchanged")
            self.assertFalse(connections.private_path("test-local").exists())


class GitOpsTests(unittest.TestCase):
    def test_application_health_is_independent_of_workload_kind_and_endpoints(self):
        desired = application()
        local.application_ready(deepcopy(desired), desired)
        for mutation in ("revision", "source", "destination", "health", "sync", "error", "running"):
            actual = deepcopy(desired)
            if mutation == "revision": actual["status"]["sync"]["revision"] = "b" * 40
            elif mutation == "source": actual["spec"]["source"]["path"] = "wrong"
            elif mutation == "destination": actual["spec"]["destination"]["namespace"] = "wrong"
            elif mutation == "health": actual["status"]["health"]["status"] = "Progressing"
            elif mutation == "sync": actual["status"]["sync"]["status"] = "OutOfSync"
            elif mutation == "error": actual["status"]["conditions"] = [{"type": "ComparisonError"}]
            else: actual["status"]["operationState"] = {"phase": "Running"}
            with self.subTest(mutation=mutation), self.assertRaises(configuration.OpsError):
                local.application_ready(actual, desired)

    def test_verify_reads_only_nodes_argo_and_applications(self):
        driver = local.Driver(args())
        root = application("startup-devops-root")
        child = application()
        def kube(*command):
            if "application" in command:
                return subprocess.CompletedProcess([], 0, json.dumps(root if "startup-devops-root" in command else child), "")
            return subprocess.CompletedProcess([], 0, "", "")
        with patch.object(driver, "kubernetes", return_value=nullcontext()), patch.object(driver, "kube", side_effect=kube) as read, redirect_stdout(io.StringIO()):
            driver.verify(root, [child])
        commands = [call.args for call in read.call_args_list]
        self.assertFalse(any("--raw" in command or "pods" in command or "demo-api" in command for command in commands))
        self.assertTrue(any("node" in command for command in commands))

    def test_verify_existing_deployment_ignores_configured_floating_revision_and_preserves_helm_inputs(self):
        root = application("startup-devops-root")
        root["spec"]["source"]["helm"] = {"parameters": [{"name": "an.existing.setting", "value": "preserved"}]}
        with patch.object(cli.shutil, "which", return_value="/fixture/tool"), patch.object(local, "Driver") as driver_class, patch.object(local, "source", return_value=nullcontext((COMMIT, ROOT))) as source, patch.object(local, "root_application", return_value=deepcopy(root)), patch.object(cli, "children_for", return_value=[application()]):
            driver = driver_class.return_value
            driver.deployed_root.return_value = root
            self.assertEqual(cli.main(["verify"]), 0)
            self.assertEqual(source.call_args.args[0].revision, COMMIT)
            self.assertEqual(driver.verify.call_args.args[0]["spec"]["source"]["helm"], root["spec"]["source"]["helm"])
            driver.deploy.assert_not_called()
            driver.create.assert_not_called()

    def test_source_preflight_failure_does_not_create_cluster(self):
        with patch.object(cli.shutil, "which", return_value="/fixture/tool"), patch.object(local, "source", side_effect=configuration.OpsError("missing source")), patch.object(local, "Driver") as driver, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["up", "--revision", "main"]), 1)
            driver.return_value.create.assert_not_called()

    def test_up_only_bootstraps_and_hands_off_to_gitops(self):
        root = application("startup-devops-root")
        with patch.object(cli.shutil, "which", return_value="/fixture/tool"), patch.object(local, "source", return_value=nullcontext((COMMIT, ROOT))), patch.object(local, "root_application", return_value=root), patch.object(cli, "children_for", return_value=[application()]), patch.object(local, "Driver") as driver_class, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["up", "--revision", "main"]), 0)
            calls = [call[0] for call in driver_class.return_value.method_calls]
            self.assertEqual(calls, ["create", "install", "deploy", "verify"])

    @unittest.skipUnless(shutil.which("helm"), "Helm required for real render")
    def test_default_root_renders_all_children_at_pinned_commit(self):
        value = args("deploy", "--revision", "main")
        root = local.root_application(value, COMMIT, ROOT)
        children = cli.children_for(root, ROOT, value, COMMIT)
        self.assertGreater(len(children), 1)
        for child in children:
            if child["spec"]["source"]["repoURL"] == value.repo_url:
                self.assertEqual(child["spec"]["source"]["targetRevision"], COMMIT)

    @unittest.skipUnless(shutil.which("helm"), "Helm required for real render")
    def test_previous_demo_root_inputs_remain_renderable_for_readonly_verification(self):
        from tests.ops import test_demo_api
        # unittest discover can import the same test package as ops instead.
        demo = test_demo_api.local
        old_root = demo.root_application(demo.parser().parse_args(["deploy", "--revision", "main"]), COMMIT)
        value = args()
        children = cli.children_for(old_root, ROOT, value, COMMIT)
        child = next(child for child in children if child["metadata"]["name"] == "demo-api")
        params = {item["name"]: item["value"] for item in child["spec"]["source"]["helm"]["parameters"]}
        self.assertEqual(params["image.tag"], "local-" + COMMIT[:12])
        self.assertEqual(params["delivery.sourceCommit"], COMMIT)

    @unittest.skipUnless(shutil.which("helm"), "Helm required for real render")
    def test_custom_application_without_demo_or_http_contract_renders_and_fetches(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            chart = repo / "gitops"
            (chart / "templates").mkdir(parents=True)
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: fixture\nversion: 0.1.0\n")
            (chart / "templates/custom.yaml").write_text(yaml.safe_dump(application()))
            root = application("startup-devops-root")
            root["spec"]["source"]["path"] = "gitops"
            (repo / "root.yaml").write_text(yaml.safe_dump(root))
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "custom GitOps only"], cwd=repo, check=True)
            expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            value = args("deploy", "--revision", "HEAD")
            value.repo_url = str(repo)  # Local Git fixture, not a supported CLI URL.
            value.root_manifest = "root.yaml"
            value.parameters = {}
            with local.source(value) as (commit, checkout):
                self.assertEqual(commit, expected)
                fetched = local.root_application(value, commit, checkout)
                children = local.render_children(fetched, checkout)
                self.assertEqual([child["metadata"]["name"] for child in children], ["custom-workload"])
                self.assertFalse((checkout / "apps/demo-api").exists())


if __name__ == "__main__":
    unittest.main()
