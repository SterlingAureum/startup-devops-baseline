"""Explicit kind lifecycle for this repository's local demo; no AWS operations."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE_REPOSITORY = "startup-devops-baseline/demo-api"
COMMANDS = ("doctor", "create", "install-argocd", "build", "deploy", "status", "verify", "destroy", "up")
STEPS = {
    "doctor": ["check installed tools"],
    "create": ["check kind cluster", "create if absent", "wait for nodes"],
    "install-argocd": ["read private kind kubeconfig", "install pinned Argo CD", "wait for controllers"],
    "build": ["require clean committed source", "build or reuse commit-tagged image", "load into named kind cluster"],
    "deploy": ["verify pushed source matches clean checkout", "verify local image source label", "apply pinned root Application"],
    "status": ["read named kind cluster nodes and Argo Applications"],
    "verify": ["resolve requested or already deployed source commit", "render configuration from that fetched commit", "wait for root and expected child Applications", "check demo rollout and ready Pods", "check demo HTTP and metrics through Service proxy"],
    "destroy": ["require exact cluster-name confirmation", "delete only named kind cluster"],
    "up": ["verify pushed source before creating resources", "create", "install-argocd", "build", "deploy", "verify"],
}


class LocalError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LocalError(message)


def integer_counter(value, field):
    # CRDs can expose counters as JSON strings. Accept only nonnegative whole
    # numbers; int(True) and int(1.5) must not turn invalid status into success.
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        try:
            return int(value)
        except ValueError:
            pass
    raise LocalError(f"{field} must be a nonnegative integer or decimal integer string")


def run(args, *, cwd=ROOT, input=None, check=True, timeout=900, env=None):
    print("+ " + shlex.join([str(arg) for arg in args]), flush=True)
    return subprocess.run(args, cwd=cwd, input=input, text=True, capture_output=True, check=check, timeout=timeout, env=env)


def validate_options(args):
    require(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", args.cluster), "Use a lowercase kind cluster name, at most 63 characters")
    require(1 <= args.http_port <= 65535 and 1 <= args.https_port <= 65535 and args.http_port != args.https_port, "Use two distinct valid host ports")
    require(args.timeout > 0, "Timeout must be positive")
    if args.revision:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.revision) is not None and ".." not in args.revision, "Use a branch, tag or full commit SHA")
    url = urlsplit(args.repo_url)
    require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment, "Use a credential-free HTTPS Git URL")
    if args.command in ("deploy", "up"):
        require(bool(args.revision), "Supply --revision for a pushed branch, tag or commit")
    if args.command == "destroy":
        require(args.confirm == args.cluster, "Destroy requires --confirm equal to --cluster")


def tools_for(command):
    return {
        "doctor": ("docker", "kind", "kubectl", "git", "helm"),
        "create": ("docker", "kind", "kubectl"),
        "install-argocd": ("kind", "kubectl"),
        "build": ("docker", "kind", "git"),
        "deploy": ("docker", "kind", "kubectl", "git"),
        "status": ("kind", "kubectl"),
        "verify": ("kind", "kubectl", "git", "helm"),
        "destroy": ("kind",),
        "up": ("docker", "kind", "kubectl", "git", "helm"),
    }[command]


def clean_commit():
    require(not run(["git", "status", "--porcelain"]).stdout.strip(), "Commit all changes before building or deploying this local GitOps path")
    return run(["git", "rev-parse", "HEAD"]).stdout.strip()


def fetch_source(args, directory):
    run(["git", "init", "-q", str(directory)])
    run(["git", "fetch", "--depth=1", "--no-tags", args.repo_url, args.revision], cwd=directory, timeout=args.timeout)
    remote = run(["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=directory).stdout.strip()
    for path in ("clusters/local/platform/Chart.yaml", "apps/demo-api/helm/Chart.yaml", "scripts/ops/local.py"):
        run(["git", "cat-file", "-e", f"{remote}:{path}"], cwd=directory)
    return remote


def source_commit(args):
    local = clean_commit()
    with tempfile.TemporaryDirectory(prefix="baseline-source-") as directory:
        remote = fetch_source(args, directory)
        require(local == remote, "The pushed source revision must match this clean checkout; checkout and push the intended commit first")
    return local


@contextmanager
def verification_source(args):
    # Read-only acceptance can use a fixed verifier with an older deployed
    # release. Render that release's checked-out chart, never the verifier's tree.
    with tempfile.TemporaryDirectory(prefix="baseline-verify-source-") as directory:
        commit = fetch_source(args, directory)
        run(["git", "checkout", "--quiet", "--detach", commit], cwd=directory)
        yield commit, Path(directory)


def image_for(commit):
    return f"{IMAGE_REPOSITORY}:local-{commit[:12]}"


def local_parameters(args, commit):
    repository = urlsplit(args.repo_url).path.strip("/").removesuffix(".git")
    require(bool(repository), "Git URL must include a repository path")
    return {
        "git.repoURL": args.repo_url, "git.targetRevision": commit,
        "demoApi.localImage.enabled": "true", "demoApi.localImage.repository": IMAGE_REPOSITORY,
        "demoApi.localImage.tag": f"local-{commit[:12]}", "demoApi.localImage.pullPolicy": "Never",
        "demoApi.localImage.applicationVersion": f"local-{commit[:12]}",
        "demoApi.localImage.sourceCommit": commit, "demoApi.localImage.sourceRepository": repository,
        "demoApi.rehearsalFault.mode": "disabled", "demoApi.rehearsalFault.tokenSha256": "",
    }


def root_application(args, commit):
    doc = yaml.safe_load((ROOT / "clusters/local/root-app.yaml").read_text())
    doc["spec"]["source"].update({"repoURL": args.repo_url, "targetRevision": commit})
    doc["spec"]["source"]["helm"]["parameters"] = [
        {"name": name, "value": value, "forceString": not name.endswith(".enabled")}
        for name, value in local_parameters(args, commit).items()
    ]
    return doc


class Driver:
    def __init__(self, args):
        self.args = args
        self.kubeconfig = None

    def clusters(self):
        return run(["kind", "get", "clusters"], timeout=self.args.timeout).stdout.splitlines()

    @contextmanager
    def kubernetes(self):
        require(self.args.cluster in self.clusters(), "Named kind cluster is absent; run create first")
        with tempfile.TemporaryDirectory(prefix="baseline-kube-") as directory:
            path = Path(directory) / "config"
            path.write_text(run(["kind", "get", "kubeconfig", "--name", self.args.cluster]).stdout)
            path.chmod(0o600)
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
                run(["kind", "create", "cluster", "--name", self.args.cluster, "--config", "-", "--wait", f"{self.args.timeout}s"],
                    input=yaml.safe_dump(config), timeout=self.args.timeout,
                    env={**os.environ, "KUBECONFIG": str(Path(directory) / "config")})
        with self.kubernetes():
            self.kube("wait", "--for=condition=Ready", "node", "--all", f"--timeout={self.args.timeout}s")

    def install(self):
        with self.kubernetes():
            namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "argocd"}}
            self.kube("apply", "-f", "-", input=yaml.safe_dump(namespace))
            self.kube("apply", "--server-side", "-n", "argocd", "-f", self.args.argocd_manifest)
            for workload in ("deployment/argocd-redis", "deployment/argocd-repo-server", "deployment/argocd-server",
                             "deployment/argocd-applicationset-controller", "statefulset/argocd-application-controller"):
                self.kube("-n", "argocd", "rollout", "status", workload, f"--timeout={self.args.timeout}s")

    def image_label(self, image, *, check=True):
        return run(["docker", "image", "inspect", "--format", '{{ index .Config.Labels "org.opencontainers.image.revision" }}', image], check=check)

    def build(self, commit):
        require(self.args.cluster in self.clusters(), "Named kind cluster is absent; run create first")
        image = image_for(commit)
        result = self.image_label(image, check=False)
        if result.returncode == 0:
            require(result.stdout.strip() == commit, "Existing local tag has a different source label; use a new source commit or explicitly remove that local image")
        else:
            run(["docker", "build", "--target", "runtime", "--label", f"org.opencontainers.image.revision={commit}",
                 "--tag", image, "apps/demo-api"], timeout=self.args.timeout)
        run(["kind", "load", "docker-image", image, "--name", self.args.cluster], timeout=self.args.timeout)
        print("Local image: " + image)

    def deploy(self, commit):
        require(self.image_label(image_for(commit)).stdout.strip() == commit, "Build and load the matching source image first")
        # Reload on deploy so a recreated kind cluster cannot use an absent image.
        run(["kind", "load", "docker-image", image_for(commit), "--name", self.args.cluster], timeout=self.args.timeout)
        with self.kubernetes():
            self.kube("get", "namespace", "argocd")
            self.kube("apply", "-f", "-", input=yaml.safe_dump(root_application(self.args, commit)))

    def status(self):
        with self.kubernetes():
            print(self.kube("get", "nodes", "-o", "wide").stdout)
            print(self.kube("-n", "argocd", "get", "applications.argoproj.io").stdout)

    def deployed_revision(self):
        with self.kubernetes():
            root = json.loads(self.kube("-n", "argocd", "get", "application", "startup-devops-root", "-o", "json").stdout)
        source = root["spec"]["source"]
        require(source.get("repoURL") == self.args.repo_url, "Deployed root repository differs; supply the original --repo-url")
        commit = source.get("targetRevision", "")
        require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit), "Deployed root must pin a full commit SHA; supply --revision explicitly for a floating root")
        return commit

    def verify(self, commit, source_root=ROOT):
        helm = ["helm", "template", "local-platform", "clusters/local/platform"]
        for name, value in local_parameters(self.args, commit).items():
            helm += ["--set" if name.endswith(".enabled") else "--set-string", name + "=" + value]
        children = [item for item in yaml.safe_load_all(run(helm, cwd=source_root).stdout) if item and item.get("kind") == "Application"]
        require(bool(children), "Local platform did not render any child Applications")
        with self.kubernetes():
            deadline = time.monotonic() + self.args.timeout
            while True:
                try:
                    root = json.loads(self.kube("-n", "argocd", "get", "application", "startup-devops-root", "-o", "json").stdout)
                    require(root.get("status", {}).get("sync", {}).get("revision") == commit, "Root Application has not reconciled the requested commit")
                    apps = [root]
                    for child in children:
                        actual = json.loads(self.kube("-n", "argocd", "get", "application", child["metadata"]["name"], "-o", "json").stdout)
                        desired = child["spec"]["source"]
                        for key in ("repoURL", "targetRevision", "path", "chart"):
                            require(actual.get("spec", {}).get("source", {}).get(key) == desired.get(key), "Child Application source differs from the requested configuration")
                        if desired.get("repoURL") == self.args.repo_url:
                            require(actual.get("status", {}).get("sync", {}).get("revision") == commit, "Child Application has not reconciled the requested commit")
                        apps.append(actual)
                    workload = json.loads(self.kube("-n", "startup-apps", "get", "rollout", "demo-api", "-o", "json").stdout)
                    labels = workload["spec"]["selector"]["matchLabels"]
                    selector = ",".join(f"{key}={value}" for key, value in sorted(labels.items()))
                    pods = json.loads(self.kube("-n", "startup-apps", "get", "pods", "-l", selector, "-o", "json").stdout)
                    verify_state(apps, workload, pods, commit)
                    prefix = "/api/v1/namespaces/startup-apps/services/demo-api-stable:http/proxy"
                    for endpoint, status in (("health", "ok"), ("ready", "ready")):
                        result = json.loads(self.kube("get", "--raw", prefix + "/" + endpoint).stdout)
                        require(result.get("status") == status, "Demo HTTP readiness check failed")
                    version = json.loads(self.kube("get", "--raw", prefix + "/version").stdout)
                    require(version.get("environment") == "local" and version.get("version") == f"local-{commit[:12]}", "Demo HTTP version does not match the local source")
                    metrics = self.kube("get", "--raw", prefix + "/metrics").stdout
                    require("demo_api_http_requests_total{" in metrics, "Demo metrics endpoint has no request series")
                    print("PASS: local Applications, rollout, Pods, HTTP version and demo metrics endpoint")
                    return
                except (LocalError, subprocess.CalledProcessError, KeyError, ValueError) as error:
                    if time.monotonic() >= deadline:
                        raise LocalError("Local verification timed out: " + str(error)) from error
                    print("Waiting for local convergence: " + str(error), flush=True)
                    time.sleep(min(5, max(0, deadline - time.monotonic())))

    def destroy(self):
        require(self.args.confirm == self.args.cluster, "Destroy requires the exact kind cluster name")
        if self.args.cluster in self.clusters():
            with tempfile.TemporaryDirectory(prefix="baseline-delete-") as directory:
                run(["kind", "delete", "cluster", "--name", self.args.cluster], timeout=self.args.timeout,
                    env={**os.environ, "KUBECONFIG": str(Path(directory) / "config")})
        print("Named kind cluster is absent; local Docker images are retained")


def verify_state(apps, workload, pods, commit):
    for app in apps:
        status = app.get("status", {})
        require(status.get("sync", {}).get("status") == "Synced" and status.get("health", {}).get("status") == "Healthy", "An expected Argo Application is not Synced and Healthy")
    status = workload.get("status", {})
    desired = integer_counter(workload["spec"].get("replicas", 1), "spec.replicas")
    generation = integer_counter(workload["metadata"]["generation"], "metadata.generation")
    observed = integer_counter(status.get("observedGeneration", 0), "status.observedGeneration")
    ready = integer_counter(status.get("readyReplicas", 0), "status.readyReplicas")
    updated = integer_counter(status.get("updatedReplicas", 0), "status.updatedReplicas")
    require(desired > 0 and observed >= generation, "Demo workload generation has not been observed")
    require(status.get("phase") == "Healthy" and ready >= desired and updated >= desired, "Demo rollout is incomplete or paused")
    active = [pod for pod in pods.get("items", []) if not pod.get("metadata", {}).get("deletionTimestamp")]
    require(len(active) >= desired, "Not enough active demo Pods")
    for pod in active:
        require(pod.get("metadata", {}).get("annotations", {}).get("platform.startup.dev/source-commit") == commit, "A demo Pod belongs to another source commit")
        containers = pod.get("spec", {}).get("containers", [])
        require(any(item.get("name") == "demo-api" and item.get("image") == image_for(commit) for item in containers), "A demo Pod uses another image")
        statuses = pod.get("status", {}).get("containerStatuses", [])
        require(any(item.get("name") == "demo-api" and item.get("ready") is True and item.get("imageID") for item in statuses), "A demo container is not ready")
        require(pod.get("status", {}).get("phase") == "Running" and any(item.get("type") == "Ready" and item.get("status") == "True" for item in pod.get("status", {}).get("conditions", [])), "A demo Pod is not ready")


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=COMMANDS)
    value.add_argument("--cluster", default="startup-devops-baseline")
    value.add_argument("--repo-url", default="https://github.com/SterlingAureum/startup-devops-baseline.git")
    value.add_argument("--revision", help="Pushed branch/tag/SHA; verify defaults to the deployed root's pinned commit")
    value.add_argument("--confirm")
    value.add_argument("--timeout", type=int, default=900)
    value.add_argument("--http-port", type=int, default=8080)
    value.add_argument("--https-port", type=int, default=8443)
    value.add_argument("--node-image", default="kindest/node:v1.30.0")
    value.add_argument("--argocd-manifest", default="https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.2/manifests/install.yaml")
    value.add_argument("--dry-run", action="store_true", help="Show targets and phases without invoking any tools")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        validate_options(args)
        if args.dry_run:
            print(json.dumps({"command": args.command, "cluster": args.cluster, "context": "kind-" + args.cluster,
                              "revision": args.revision, "steps": STEPS[args.command], "executed": False}, indent=2))
            return 0
        missing = [name for name in tools_for(args.command) if shutil.which(name) is None]
        require(not missing, "Missing tools: " + ", ".join(missing))
        driver = Driver(args)
        commit = None
        if args.command == "verify":
            if not args.revision:
                args.revision = driver.deployed_revision()
            with verification_source(args) as (commit, source_root):
                driver.verify(commit, source_root=source_root)
            return 0
        if args.command in ("deploy", "up"):
            commit = source_commit(args)
        elif args.command == "build":
            commit = clean_commit()
        if args.command == "up":
            driver.create(); driver.install(); driver.build(commit); driver.deploy(commit); driver.verify(commit)
        elif args.command == "doctor":
            print("Required tools are installed; runtime and network readiness are checked by their commands")
        elif args.command == "install-argocd":
            driver.install()
        elif args.command in ("build", "deploy", "verify"):
            getattr(driver, args.command)(commit)
        else:
            getattr(driver, args.command)()
        return 0
    except (LocalError, OSError, subprocess.SubprocessError, yaml.YAMLError, KeyError, ValueError) as error:
        print("FAILED: " + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
