"""Bootstrap the standard GitOps stack on a provisioned personal dev cluster."""
import json
import os
import secrets
import subprocess
import tempfile
import time

import yaml

from aws_preflight import inspect, kustomize, local_file
from configuration import DEFAULT_CONFIG, ROOT, OpsError, environment, load_yaml, require
from connections import atomic_write, private_path

PHASES = ["check personal inventory, remote Terraform outputs and live EKS identity",
          "refresh dedicated kubeconfig", "prepare IRSA and Grafana credentials",
          "install pinned Argo CD and seed ALB Application", "sync dev root and CNPG backup destination",
          "seed standard demo credential and reconcile DNS", "wait for GitOps applications"]
ARGO = "argocd"


def run(argv, env, data=None, private=False):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, env=env)
    if result.returncode:
        detail = "private payload suppressed" if private else result.stderr.strip()
        raise OpsError(f"{argv[0]} failed: {detail}")
    return result.stdout


class Cluster:
    def __init__(self, context, env, timeout):
        self.context = context
        self.env = env
        self.timeout = timeout
        self.path = private_path("aws-dev")

    def aws(self, *args, data=None, private=False):
        return run(["aws", *args, "--output", "json"], self.env, data, private)

    def k(self, *args, data=None, private=False):
        return run(["kubectl", "--kubeconfig", str(self.path), "--context", self.context,
                    *args], self.env, data, private)

    def obj(self, ns, resource):
        raw = self.k("-n", ns, "get", resource, "--ignore-not-found", "--request-timeout=30s", "-o", "json")
        return json.loads(raw) if raw.strip() else None

    def until(self, description, read):
        print("Waiting for " + description, flush=True)
        deadline = time.monotonic() + self.timeout
        while True:
            value = read()
            if value:
                return value
            if time.monotonic() >= deadline:
                raise OpsError(f"Timed out: {description}. Inspect Applications and events with {self.path}")
            time.sleep(5)

    def exists(self, ns, resource):
        return self.until(ns + "/" + resource, lambda: self.obj(ns, resource))

    def ready(self, ns, resource, condition="Ready"):
        self.exists(ns, resource)
        self.k("-n", ns, "wait", "--for=condition=" + condition, resource, f"--timeout={self.timeout}s")

    def apply(self, document):
        self.k("apply", "-f", "-", data=json.dumps(document))

    def namespace(self, name, labels=None):
        self.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": labels or {}}})

    def irsa(self, ns, name, arn):
        self.apply({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {
            "name": name, "namespace": ns, "annotations": {"eks.amazonaws.com/role-arn": arn}}})


def prepare(g, out):
    g.namespace(ARGO)
    g.namespace("observability")
    g.namespace("external-secrets", {"pod-security.kubernetes.io/enforce": "restricted",
                                     "pod-security.kubernetes.io/enforce-version": "v1.30",
                                     "pod-security.kubernetes.io/warn": "restricted",
                                     "pod-security.kubernetes.io/audit": "restricted"})
    g.namespace("data-platform")
    for ns, name, key in [
        ("kube-system", "aws-load-balancer-controller", "aws_load_balancer_controller_role_arn"),
        ("kube-system", "karpenter", "karpenter_controller_role_arn"),
        ("external-secrets", "external-secrets", "external_secrets_role_arn"),
        ("data-platform", "postgresql-baseline", "cnpg_backup_role_arn"),
    ]:
        g.irsa(ns, name, out[key])

    name = "observability-grafana-admin"
    existing = g.obj("observability", "secret/" + name)
    if existing is None:
        document = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name},
                    "stringData": {"admin-user": "admin", "admin-password": secrets.token_urlsafe(36)}}
        g.k("-n", "observability", "create", "-f", "-", data=json.dumps(document), private=True)
    else:
        require(all(existing.get("data", {}).get(k) for k in ("admin-user", "admin-password")),
                "Existing Grafana Secret is missing an admin key")


def gitops(g, report, out, argo_manifest):
    root = load_yaml((ROOT / report["gitops_root"]).read_text())
    children = {doc["metadata"]["name"]: doc for doc in kustomize(root["spec"]["source"]["path"])
                if doc and doc["kind"] == "Application"}
    g.k("apply", "-n", ARGO, "--server-side", "-f", argo_manifest)
    for resource in ("deployment/argocd-repo-server", "deployment/argocd-server",
                     "statefulset/argocd-application-controller"):
        g.k("-n", ARGO, "rollout", "status", resource, f"--timeout={g.timeout}s")

    alb = children["aws-load-balancer-controller"]
    alb["spec"]["source"]["helm"]["valuesObject"]["vpcId"] = out["vpc_id"]
    g.apply(alb)
    g.apply(root)
    g.ready("data-platform", "crd/objectstores.barmancloud.cnpg.io", "Established")
    resource = "objectstores.barmancloud.cnpg.io/postgresql-baseline-backup"
    store = g.exists("data-platform", resource)
    destination = "s3://" + out["cnpg_backup_bucket_name"] + "/postgresql-baseline"
    current = store["spec"]["configuration"]["destinationPath"]
    if current != destination:
        require(current == "s3://__CNPG_BACKUP_BUCKET__/postgresql-baseline", "Unexpected live backup destination")
        path = "/spec/configuration/destinationPath"
        patch = [{"op": "test", "path": path, "value": current}, {"op": "replace", "path": path, "value": destination}]
        g.k("-n", "data-platform", "patch", resource, "--type=json", "-p", json.dumps(patch))
    g.ready("data-platform", "crd/clusters.postgresql.cnpg.io", "Established")
    g.ready("data-platform", "clusters.postgresql.cnpg.io/postgresql-baseline")
    return set(children) | {root["metadata"]["name"]}


def check_apps(g, names):
    last = None

    def converged():
        nonlocal last
        apps = json.loads(g.k("-n", ARGO, "get", "applications", "-o", "json"))["items"]
        healthy = {app["metadata"]["name"] for app in apps
                   if app.get("status", {}).get("sync", {}).get("status") == "Synced"
                   and app["status"].get("health", {}).get("status") == "Healthy"}
        pending = sorted(names - healthy)
        if pending != last and pending:
            print("Pending Applications: " + ", ".join(pending), flush=True)
        last = pending
        return not pending
    g.until("expected dev Applications to be Synced and Healthy", converged)


def deploy(env, config):
    from aws_standard_demo import complete
    report = inspect("aws-dev", env, config, personal=True)
    aws = env["aws"]
    settings = dict(os.environ, AWS_REGION=aws["region"], AWS_DEFAULT_REGION=aws["region"], AWS_PAGER="")
    if aws.get("profile"):
        settings["AWS_PROFILE"] = aws["profile"]
    g = Cluster(report["cluster"], settings, env.get("timeout", 1800))
    caller = json.loads(g.aws("sts", "get-caller-identity"))
    require(caller["Account"] == aws["expected_account_id"], "AWS caller account differs from inventory")
    if aws.get("role_arn"):
        name = aws["role_arn"].rsplit("/", 1)[-1]
        require(caller["Arn"].startswith(f"arn:aws:sts::{caller['Account']}:assumed-role/{name}/"),
                "Select operator credentials for the configured role")
    tf = env["terraform"]
    backend = local_file(tf["backend_file"], config.expanduser().resolve().parent)
    with tempfile.TemporaryDirectory(prefix="aws-dev-deploy-") as tmp:
        tfenv = dict(settings, TF_DATA_DIR=tmp + "/terraform", TF_WORKSPACE="default")
        terraform = ["terraform", "-chdir=" + str(ROOT / tf["root"])]
        run(terraform + ["init", "-input=false", "-backend-config=" + str(backend)], tfenv)
        outputs = json.loads(run(terraform + ["output", "-json"], tfenv, private=True))
        out = {key: value["value"] for key, value in outputs.items()}
        require(out["environment_name"] == "dev" and out["eks_cluster_name"] == g.context,
                "Terraform output cluster differs from inventory")
        live = json.loads(g.aws("eks", "describe-cluster", "--name", g.context))["cluster"]
        require(live["status"] == "ACTIVE" and live["endpoint"] == out["eks_cluster_endpoint"]
                and live["resourcesVpcConfig"]["vpcId"] == out["vpc_id"], "Live EKS differs from Terraform")
        raw = run(["aws", "eks", "update-kubeconfig", "--dry-run", "--alias", g.context,
                   "--name", g.context, "--kubeconfig", tmp + "/config"], settings)
        kube = yaml.safe_load(raw)
        require(kube["current-context"] == g.context and kube["clusters"][0]["cluster"]["server"] == live["endpoint"],
                "Generated kubeconfig differs from EKS")
        atomic_write(g.path, raw)
    print(f"Dedicated kubeconfig: {g.path}", flush=True)
    g.k("get", "nodes")
    prepare(g, out)
    argocd = env.get("argocd", environment(DEFAULT_CONFIG, "local")["argocd"])
    require(argocd["namespace"] == ARGO, "AWS root requires the argocd namespace")
    names = gitops(g, report, out, argocd["manifest"])
    complete(g, out)
    check_apps(g, names)
    print("AWS dev GitOps stack converged. Runtime qualification is a separate workflow.")
