"""kind lifecycle backend. Business workloads and HTTP checks belong to applications."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

import yaml

from configuration import ROOT, OpsError, load_yaml, repository_path, require
import connections

LocalError = OpsError
ARGO_WORKLOADS = ("deployment/argocd-redis", "deployment/argocd-repo-server", "deployment/argocd-server",
                  "deployment/argocd-applicationset-controller", "statefulset/argocd-application-controller")


def run(args, *, cwd=ROOT, input=None, check=True, timeout=900, env=None):
    print("+ " + shlex.join([str(arg) for arg in args]), flush=True)
    return subprocess.run(args, cwd=cwd, input=input, text=True, capture_output=True, check=check, timeout=timeout, env=env)


def source_path(directory, name):
    repository_path(name, "GitOps source path")
    base = Path(directory).resolve()
    path = (base / name).resolve()
    require(path.is_relative_to(base), "GitOps path escapes the fetched repository")
    return path


@contextmanager
def source(args):
    with tempfile.TemporaryDirectory(prefix="baseline-gitops-") as directory:
        run(["git", "init", "-q", directory])
        run(["git", "fetch", "--depth=1", "--no-tags", args.repo_url, args.revision], cwd=directory, timeout=args.timeout)
        commit = run(["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=directory).stdout.strip()
        require(re.fullmatch(r"[0-9a-f]{40}", commit), "Expected a full source commit SHA")
        run(["git", "checkout", "--quiet", "--detach", commit], cwd=directory)
        yield commit, Path(directory)


def root_application(args, commit, directory):
    doc = load_yaml(source_path(directory, args.root_manifest).read_text())
    require(isinstance(doc, dict) and doc.get("apiVersion") == "argoproj.io/v1alpha1" and doc.get("kind") == "Application", "GitOps root manifest must be one Argo CD Application")
    require(doc.get("metadata", {}).get("name") == args.root_application and doc["metadata"].get("namespace", args.argocd_namespace) == args.argocd_namespace, "GitOps root identity differs from environment configuration")
    doc["metadata"]["namespace"] = args.argocd_namespace
    spec = doc["spec"]
    require("sources" not in spec and isinstance(spec.get("source"), dict) and spec["source"].get("path"), "Initial lifecycle supports one repository-backed root source")
    require(spec.get("destination", {}).get("server") == "https://kubernetes.default.svc", "GitOps root must target this cluster")
    repository_path(spec["source"]["path"], "root source.path")
    spec["source"].update({"repoURL": args.repo_url, "targetRevision": commit})
    if args.parameters:
        helm = spec["source"].setdefault("helm", {})
        parameters = {item["name"]: item for item in helm.get("parameters", [])}
        for name, value in args.parameters.items():
            value = value.replace("${repository}", args.repo_url).replace("${revision}", commit)
            parameters[name] = {"name": name, "value": value, "forceString": True}
        helm["parameters"] = list(parameters.values())
    return doc


def helm_parameters(parameters):
    """Restore only HelmParameter API defaults omitted by Go JSON serialization."""
    require(isinstance(parameters, list), "Helm parameters must be a list")
    result = []
    for parameter in parameters:
        require(isinstance(parameter, dict), "A Helm parameter must be a mapping")
        name = parameter.get("name")
        require(isinstance(name, str) and bool(name), "A Helm parameter must have a nonempty name")
        value = parameter.get("value", "")
        force_string = parameter.get("forceString", False)
        require(isinstance(value, str), "Helm parameter " + name + " value must be a string")
        require(type(force_string) is bool, "Helm parameter " + name + " forceString must be a boolean")
        result.append({**parameter, "value": value, "forceString": force_string})
    return result


def comparable_helm(helm):
    # Do not mutate the live or rendered source, drop parameters, sort duplicate
    # names, or normalize actual value differences into a passing comparison.
    require(helm is None or isinstance(helm, dict), "Helm source must be a mapping")
    result = dict(helm or {})
    result["parameters"] = helm_parameters(result.get("parameters", []))
    return result


def render_children(root, directory):
    src = root["spec"]["source"]
    chart = source_path(directory, src["path"])
    require((chart / "Chart.yaml").is_file(), "Initial lifecycle expects a Helm app-of-apps root; Kustomize/multi-source support is pending")
    helm = src.get("helm", {})
    require(not helm.get("fileParameters"), "Helm fileParameters are outside this initial root adapter")
    command = ["helm", "template", helm.get("releaseName", root["metadata"]["name"]), str(chart), "--namespace", root["metadata"]["namespace"]]
    for file in helm.get("valueFiles", []):
        value_path = source_path(directory, str(Path(src["path"]) / file))
        require(value_path.is_file(), "Root values file is absent")
        command += ["-f", str(value_path)]
    with tempfile.TemporaryDirectory(prefix="baseline-values-") as temporary:
        for key in ("values", "valuesObject"):
            if key in helm:
                file = Path(temporary) / (key + ".yaml")
                file.write_text(yaml.safe_dump(helm[key]) if key == "valuesObject" else helm[key])
                command += ["-f", str(file)]
        for parameter in helm_parameters(helm.get("parameters", [])):
            command += ["--set-string" if parameter["forceString"] else "--set", parameter["name"] + "=" + parameter["value"]]
        children = [item for item in yaml.safe_load_all(run(command, cwd=directory).stdout)
                    if isinstance(item, dict) and item.get("kind") == "Application"]
    require(bool(children), "GitOps root rendered no child Applications")
    identities = set()
    for child in children:
        meta = child["metadata"]
        require(meta.get("namespace", root["metadata"]["namespace"]) == root["metadata"]["namespace"], "Child Application namespace differs from root")
        require(meta["name"] not in identities, "Duplicate child Application identity")
        identities.add(meta["name"])
        require(child.get("spec", {}).get("destination", {}).get("server") == "https://kubernetes.default.svc", "Child Application targets another cluster")
    return children


def application_ready(actual, desired):
    require(not actual.get("metadata", {}).get("deletionTimestamp"), "An expected Application is being deleted")
    require(actual.get("spec", {}).get("destination") == desired["spec"].get("destination"), "Application destination differs from GitOps declaration")
    expected = desired["spec"]["source"]
    current = actual.get("spec", {}).get("source", {})
    for key, value in expected.items():
        observed = current.get(key)
        if key == "helm":
            observed, value = comparable_helm(observed), comparable_helm(value)
        require(observed == value, "Application source differs: " + key)
    status = actual.get("status", {})
    require(status.get("sync", {}).get("status") == "Synced" and status.get("health", {}).get("status") == "Healthy", "Application is not Synced and Healthy")
    revision = expected.get("targetRevision", "")
    if re.fullmatch(r"[0-9a-f]{40}", revision):
        require(status.get("sync", {}).get("revision") == revision, "Application has not reconciled the requested commit")
    require(status.get("operationState", {}).get("phase") != "Running", "Application operation is still running")
    require(not any(str(item.get("type", "")).endswith("Error") for item in status.get("conditions", [])), "Application reports an active error condition")


class Driver:
    def __init__(self, args):
        self.args = args
        self.kubeconfig = None

    def clusters(self):
        return run(["kind", "get", "clusters"], timeout=self.args.timeout).stdout.splitlines()

    def connection(self):
        require(self.args.cluster in self.clusters(), "Named kind cluster is absent; run create first")
        contents = run(["kind", "get", "kubeconfig", "--name", self.args.cluster]).stdout
        doc = connections.kind_config(contents, self.args.cluster)
        path = connections.atomic_write(connections.private_path(self.args.cluster), yaml.safe_dump(doc, sort_keys=False))
        print("Dedicated kubeconfig: " + str(path))
        return doc

    @contextmanager
    def kubernetes(self):
        doc = self.connection()
        with tempfile.TemporaryDirectory(prefix="baseline-kube-") as directory:
            path = connections.atomic_write(Path(directory) / "config", yaml.safe_dump(doc, sort_keys=False))
            self.kubeconfig = str(path)
            try:
                yield
            finally:
                self.kubeconfig = None

    def kube(self, *args, input=None):
        require(bool(self.kubeconfig), "Use an isolated kind kubeconfig")
        return run(["kubectl", "--kubeconfig", self.kubeconfig, "--context", "kind-" + self.args.cluster,
                    "--request-timeout=30s", *args], input=input, timeout=self.args.timeout)

    def create(self):
        if self.args.cluster not in self.clusters():
            config = {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "nodes": [{
                "role": "control-plane", "image": self.args.node_image,
                "extraPortMappings": [
                    {"containerPort": 80, "hostPort": self.args.http_port, "listenAddress": "127.0.0.1"},
                    {"containerPort": 443, "hostPort": self.args.https_port, "listenAddress": "127.0.0.1"},
                ],
            }]}
            with tempfile.TemporaryDirectory(prefix="baseline-create-") as directory:
                try:
                    run(["kind", "create", "cluster", "--name", self.args.cluster, "--config", "-", "--wait", f"{self.args.timeout}s"],
                        input=yaml.safe_dump(config), timeout=self.args.timeout,
                        env={**os.environ, "KUBECONFIG": str(Path(directory) / "config")})
                except subprocess.SubprocessError:
                    try:
                        self.connection()
                    except (OpsError, OSError, subprocess.SubprocessError):
                        pass
                    raise
        with self.kubernetes():
            self.kube("wait", "--for=condition=Ready", "node", "--all", f"--timeout={self.args.timeout}s")

    def argo_ready(self):
        for workload in ARGO_WORKLOADS:
            self.kube("-n", self.args.argocd_namespace, "rollout", "status", workload, f"--timeout={self.args.timeout}s")

    def install(self):
        require(self.args.argocd_namespace == "argocd", "Pinned installer supports namespace argocd; custom namespace bootstrap is pending")
        with self.kubernetes():
            namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.args.argocd_namespace}}
            self.kube("apply", "-f", "-", input=yaml.safe_dump(namespace))
            self.kube("apply", "--server-side", "-n", self.args.argocd_namespace, "-f", self.args.argocd_manifest)
            self.argo_ready()

    def deploy(self, root):
        with self.kubernetes():
            self.kube("get", "namespace", self.args.argocd_namespace)
            self.kube("apply", "-f", "-", input=yaml.safe_dump(root))

    def status(self):
        with self.kubernetes():
            print(self.kube("get", "nodes", "-o", "wide").stdout)
            print(self.kube("-n", self.args.argocd_namespace, "get", "applications.argoproj.io").stdout)

    def root(self):
        return json.loads(self.kube("-n", self.args.argocd_namespace, "get", "application", self.args.root_application, "-o", "json").stdout)

    def deployed_root(self):
        with self.kubernetes():
            root = self.root()
        require(root["spec"]["source"].get("repoURL") == self.args.repo_url, "Deployed root repository differs from selected environment")
        require(re.fullmatch(r"[0-9a-f]{40}", root["spec"]["source"].get("targetRevision", "")), "Deployed root must pin a full commit SHA; deploy a pinned source first")
        return root

    def verify(self, expected_root, children):
        with self.kubernetes():
            self.kube("wait", "--for=condition=Ready", "node", "--all", f"--timeout={self.args.timeout}s")
            self.argo_ready()
            deadline = time.monotonic() + self.args.timeout
            while True:
                name = self.args.root_application
                try:
                    application_ready(self.root(), expected_root)
                    for child in children:
                        name = child["metadata"]["name"]
                        actual = json.loads(self.kube("-n", self.args.argocd_namespace, "get", "application", name, "-o", "json").stdout)
                        application_ready(actual, child)
                    print("PASS: kind nodes, Argo controllers and declared GitOps Applications; business runtime checks are separate")
                    return
                except (OpsError, subprocess.CalledProcessError, KeyError, ValueError) as error:
                    if time.monotonic() >= deadline:
                        raise OpsError("GitOps verification timed out at " + name + ": " + str(error)) from error
                    print("Waiting for " + name + ": " + str(error), flush=True)
                    time.sleep(min(5, max(0, deadline - time.monotonic())))

    def connect(self):
        connections.connect(self.connection(), self.args.cluster, self.args.kubeconfig_file)

    def destroy(self):
        require(self.args.confirm == self.args.cluster, "Destroy requires the exact kind cluster name")
        if self.args.cluster in self.clusters():
            with tempfile.TemporaryDirectory(prefix="baseline-delete-") as directory:
                run(["kind", "delete", "cluster", "--name", self.args.cluster], timeout=self.args.timeout,
                    env={**os.environ, "KUBECONFIG": str(Path(directory) / "config")})
        connections.private_path(self.args.cluster).unlink(missing_ok=True)
        print("Named kind cluster and dedicated kubeconfig are absent; Docker images and shared kubeconfig are retained")


def main(argv=None):
    from cli import main as entrypoint
    return entrypoint(argv, local_only=True)


if __name__ == "__main__":
    sys.exit(main())
