"""Provision the personal dev Terraform root and bootstrap its standard GitOps stack."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

import yaml

from aws_preflight import inspect, kustomize, local_file
from aws_state import check_selected_state, init_argument, lifecycle_directory
from aws_standard_demo import complete
from aws_provision import provision
from configuration import ROOT, OpsError, load_yaml, require
from connections import atomic_write, aws_private_path, kubectl_hint

PHASES = ["check personal inventory, remote Terraform outputs and live EKS identity",
          "refresh dedicated kubeconfig", "check root Application and target namespaces for deletion",
          "prepare IRSA and Grafana credentials",
          "install pinned Argo CD and seed ALB Application", "sync dev root and CNPG backup destination",
          "recover the ESO consumer and reconcile the standard demo database credential",
          "wait for demo replicas using the synced credential, reconcile DNS, and check GitOps applications"]
ARGO = "argocd"


def run(argv, env, data=None, private=False):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, env=env)
    if result.returncode:
        detail = "private payload suppressed" if private else result.stderr.strip()
        raise OpsError(f"{argv[0]} failed: {detail}")
    return result.stdout


@contextmanager
def lifecycle_lock(account, region, cluster):
    folder = lifecycle_directory(account, region, cluster)
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (folder / "destroy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OpsError("Another dev deploy or destroy is running on this workstation") from error
        yield folder


def reopen_receipt(journal):
    previous = set(journal.get("prior_snapshots", [])) | set(journal["snapshots"].values())
    journal["volumes"] = sorted(set(journal.get("volumes", [])) | set(journal["snapshots"]))
    journal.update(prior_snapshots=sorted(previous), snapshots={}, cleaned=False, complete=False)


class Cluster:
    def __init__(self, context, env, timeout, path):
        self.context = context
        self.env = env
        self.timeout = timeout
        self.path = path

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


def check_deploy_target(g, root, children):
    namespaces = {ARGO, root["spec"]["destination"]["namespace"]}
    namespaces.update(child["spec"]["destination"]["namespace"] for child in children.values())
    live = json.loads(g.k("get", "namespaces", "--request-timeout=30s", "-o", "json"))["items"]
    deleting = ["namespace/" + ns["metadata"]["name"] for ns in live
                if ns["metadata"]["name"] in namespaces and
                (ns["metadata"].get("deletionTimestamp") or ns.get("status", {}).get("phase") == "Terminating")]
    # A new EKS cluster has no Argo CD CRDs yet.
    if g.obj(ARGO, "crd/applications.argoproj.io"):
        resource = "applications.argoproj.io/" + root["metadata"]["name"]
        app = g.obj(ARGO, resource)
        if app and app["metadata"].get("deletionTimestamp"):
            deleting.append(ARGO + "/" + resource)
    require(not deleting, "Deploy blocked by deletion in progress: " + ", ".join(deleting) +
            ". Finish cleanup before redeploying.")


def gitops(g, root, children, out, argo_manifest):
    controller = "statefulset/argocd-application-controller"
    existing = g.obj(ARGO, controller)
    if existing and existing["spec"].get("replicas") == 0:
        print("Resuming the suspended Argo CD application controller", flush=True)
        g.k("-n", ARGO, "scale", controller, "--replicas=1", "--current-replicas=0")
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


def deploy(selected, env, config, adopt=None, *, operation="deploy", confirm=None):
    report = inspect(selected, env, config, personal=True)
    require(operation in ("plan", "create", "up", "deploy"), "Unknown AWS provisioning operation")
    require(confirm is None or (operation in ("up", "create") and confirm == report["cluster"]),
            "Provisioning requires --confirm " + report["cluster"])
    aws = env["aws"]
    settings = dict(os.environ, AWS_REGION=aws["region"], AWS_DEFAULT_REGION=aws["region"], AWS_PAGER="")
    if aws.get("profile"):
        settings["AWS_PROFILE"] = aws["profile"]
    path = aws_private_path(aws["expected_account_id"], aws["region"], report["cluster"])
    g = Cluster(report["cluster"], settings, env.get("timeout", 1800), path)
    caller = json.loads(g.aws("sts", "get-caller-identity"))
    require(caller["Account"] == aws["expected_account_id"], "AWS caller account differs from inventory")
    if aws.get("role_arn"):
        name = aws["role_arn"].rsplit("/", 1)[-1]
        require(caller["Arn"].startswith(f"arn:aws:sts::{caller['Account']}:assumed-role/{name}/"),
                "Select operator credentials for the configured role")
    with lifecycle_lock(caller["Account"], aws["region"], g.context) as folder:
        deploy_stack(g, report, env, config, folder, adopt, operation=operation, confirm=confirm)


def deploy_stack(g, report, env, config, folder, adopt=None, *, operation="deploy", confirm=None):
    settings = g.env
    tf = env["terraform"]
    base = config.expanduser().resolve().parent
    with tempfile.TemporaryDirectory(prefix="aws-dev-deploy-") as tmp:
        tfenv = dict(settings, TF_DATA_DIR=tmp + "/terraform", TF_WORKSPACE="default")
        require(not any(v for k, v in tfenv.items() if k.startswith("TF_CLI_ARGS")),
                "Unset TF_CLI_ARGS overrides before provisioning")
        if operation != "deploy":
            print(f"Initializing {tf['root']} for {g.context} (default workspace)", flush=True)
            # Use the same variable sources that personal preflight inspected.
            tfenv = {k: v for k, v in tfenv.items() if not k.startswith("TF_VAR_")}
        terraform = ["terraform", "-chdir=" + str(ROOT / tf["root"])]
        check_selected_state(g, report, operation)
        run(terraform + ["init", "-input=false", "-reconfigure", init_argument(tf["backend"], base)], tfenv)
        if operation != "deploy":
            variables = local_file(tf["variables_file"], base)
            provision(g, terraform, tfenv, variables, Path(tmp) / "create.tfplan", folder, confirm)
            if operation != "up" or confirm is None:
                return
        outputs = json.loads(run(terraform + ["output", "-json"], tfenv, private=True))
        out = {key: value["value"] for key, value in outputs.items()}
        require(out.get("eks_cluster_name"), "Dev infrastructure is absent from outputs; use plan then up for the selected inventory entry")
        require(out.get("environment_name") == "dev" and out["eks_cluster_name"] == g.context,
                "Terraform output cluster differs from inventory")
        try:
            live = json.loads(g.aws("eks", "describe-cluster", "--name", g.context))["cluster"]
        except OpsError as error:
            if "(ResourceNotFoundException)" in str(error):
                raise OpsError(f"EKS cluster {g.context} is absent; use plan then up for the selected inventory entry") from error
            raise
        require(live["status"] == "ACTIVE" and live["endpoint"] == out["eks_cluster_endpoint"]
                and live["resourcesVpcConfig"]["vpcId"] == out["vpc_id"], "Live EKS differs from Terraform")
        raw = run(["aws", "eks", "update-kubeconfig", "--dry-run", "--alias", g.context,
                   "--name", g.context, "--kubeconfig", tmp + "/config"], settings)
        kube = yaml.safe_load(raw)
        require(kube["current-context"] == g.context and kube["clusters"][0]["cluster"]["server"] == live["endpoint"],
                "Generated kubeconfig differs from EKS")
        atomic_write(g.path, raw)
        print(f"Dedicated kubeconfig: {g.path}", flush=True)
        root = load_yaml((ROOT / report["gitops_root"]).read_text())
        children = {doc["metadata"]["name"]: doc for doc in kustomize(root["spec"]["source"]["path"])
                    if doc and doc["kind"] == "Application"}
        check_deploy_target(g, root, children)
        # A successful redeploy can change data on the same EBS volume IDs.
        # Invalidate the previous cleanup checkpoint before the first cluster write.
        # Read only the lineage from the private state payload.
        if any(folder.glob("*.json")):
            state = json.loads(run(terraform + ["state", "pull"], tfenv, private=True))
            receipt = folder / (state["lineage"] + ".json")
            if receipt.exists():
                journal = json.loads(receipt.read_text())
                if journal.get("vpc") == out["vpc_id"] and journal.get("endpoint") == live["endpoint"]:
                    reopen_receipt(journal)
                    atomic_write(receipt, json.dumps(journal, indent=2))
    g.k("get", "nodes")
    prepare(g, out)
    names = gitops(g, root, children, out, env["argocd"]["manifest"])
    complete(g, out, adopt)
    check_apps(g, names)
    print(kubectl_hint(g.path, g.context))
    print("AWS dev GitOps stack converged. Runtime qualification is a separate workflow.")
