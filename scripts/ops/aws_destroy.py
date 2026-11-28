"""Teardown of the standard personal AWS stack. Preview, release and verify the selected environment."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from aws_deploy import Cluster, lifecycle_lock, reopen_receipt, run
from aws_dev_network import release_network
from aws_preflight import inspect_infrastructure, local_file
from aws_database import BUCKET, SECRET, DURABLE, DATABASE_MOVES, original, database_variables
from aws_retention import observe, report_storage
from aws_state import check_selected_state, initialize_backend
from configuration import ROOT, OpsError, require
from connections import atomic_write

PHASES = ["inspect selected account, backend, Terraform delete plan and live cluster identity",
          "pause GitOps and apply the selected backup policy", "release exact DNS alias and ingress",
          "wait for startup-apps ExternalSecrets to finalize before deleting namespaces",
          "release workloads, PVCs and Karpenter nodes while controllers are available",
          "remove EKS, release verified cluster network dependencies, then destroy the VPC and check remaining state"]
MODULES = {"eks", "vpc", "github_actions_runtime_identity", "cnpg_backup", "external_secrets",
           "tls_dns", "fis", "karpenter"}


GENERATION = "BaselineDevCreationPlan"
CLUSTER = "module.eks.aws_eks_cluster.this"


def generation(attrs):
    return (attrs.get("tags") or {}).get(GENERATION)


def creation_plan(state):
    for r in state.get("resources", []):
        if (r["mode"], r.get("module"), r["type"], r["name"]) == ("managed", "module.eks", "aws_eks_cluster", "this"):
            if len(r["instances"]) == 1:
                return generation(r["instances"][0].get("attributes", {}))
    return None


def partition(state, owner=None, retain=False):
    disposable = set()
    if owner and not retain:
        for r in state.get("resources", []):
            addr = ".".join([r.get("module", ""), r["type"], r["name"]])
            if r["mode"] == "managed" and original(addr) in (BUCKET, SECRET) and len(r["instances"]) == 1:
                attrs = r["instances"][0].get("attributes", {})
                if generation(attrs) == owner and (original(addr) != BUCKET or attrs.get("force_destroy") is True):
                    disposable.add(original(addr))

    destroy, keep = set(), set()
    for r in state.get("resources", []):
        if r["mode"] != "managed":
            continue
        module = r.get("module", "")
        require(module.startswith("module.") and (module.split(".")[1].split("[")[0] in MODULES or
                ".".join([module, r["type"], r["name"]]) in DATABASE_MOVES.values()),
                "Unexpected managed resource outside the standard environment modules: " + module)
        if module.startswith("module.github_actions_runtime_identity"):
            require(r["type"] == "aws_eks_access_entry", "Review unexpected persistent identity in selected state")
        addr = ".".join([module, r["type"], r["name"]])
        if module in ("module.cnpg_backup", "module.external_secrets") and addr not in DATABASE_MOVES:
            require(not r["instances"], f"Review unexpected database resource before teardown: {addr}")
        retained = original(addr) in DURABLE
        for instance in r["instances"]:
            suffix = "[" + json.dumps(instance["index_key"], ensure_ascii=False) + "]" if "index_key" in instance else ""
            protected = (SECRET if original(addr) == SECRET else BUCKET) not in disposable
            (keep if retained and protected else destroy).add(addr + suffix)
    return destroy, keep


def check_plan(plan, targets, owner=None):
    deletes = set()
    for change in plan.get("resource_changes", []):
        actions = change["change"]["actions"]
        if change["mode"] == "data" or actions == ["no-op"]:
            continue
        require(actions == ["delete"] and change["address"] in targets,
                f"Unexpected destroy plan action: {change['address']} {actions}")
        if original(change["address"]) in (BUCKET, SECRET) or (owner and change["address"] == CLUSTER):
            before = change["change"]["before"]
            require(owner and generation(before) == owner, "Creation marker changed during refresh: " + change["address"])
            require(original(change["address"]) != BUCKET or before.get("force_destroy") is True,
                    "Refreshed bucket does not allow removal of its objects")
        deletes.add(change["address"])
    # Drifted resources already gone in AWS need no delete action.
    gone = {c["address"] for c in plan.get("resource_drift", []) if c["change"]["actions"] == ["delete"]}
    require(targets <= deletes | gone, "Terraform omitted managed objects from the destroy plan")
    return sorted(deletes)


def resources(g, kind, *args):
    return json.loads(g.k("get", kind, *args, "--request-timeout=30s", "-o", "json"))["items"]


def storage(g):
    volumes = {}
    classes = {"gp3-cnpg": "data-platform", "gp3-observability": "observability",
               "gp3-observability-alertmanager": "observability"}
    for pv in resources(g, "pv"):
        spec = pv["spec"]
        claim = spec.get("claimRef", {})
        volume = spec.get("csi", {})
        require(spec.get("storageClassName") in classes and claim.get("namespace") == classes[spec["storageClassName"]]
                and volume.get("driver") == "ebs.csi.aws.com" and spec["persistentVolumeReclaimPolicy"] == "Delete",
                "Review unexpected persistent volume before teardown: " + pv["metadata"]["name"])
        volumes[volume["volumeHandle"]] = claim["namespace"] + "/" + claim["name"]
    return volumes


def dns_record(g, out):
    zone = out["route53_hosted_zone_id"]
    host = out["demo_api_hostname"].rstrip(".")
    rr = json.loads(g.aws("route53", "list-resource-record-sets", "--hosted-zone-id", zone))
    matches = [r for r in rr["ResourceRecordSets"] if r["Type"] == "A" and r["Name"].rstrip(".") == host]
    if not matches:
        return None
    ingress = g.obj("startup-apps", "ingress/demo-api") or {}
    names = {a.get("hostname") for a in ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])}
    record = matches[0]
    alias = record.get("AliasTarget", {})
    dns = alias.get("DNSName", "").rstrip(".").removeprefix("dualstack.")
    lbs = json.loads(g.aws("elbv2", "describe-load-balancers"))["LoadBalancers"]
    require(len(matches) == 1 and not record.get("SetIdentifier") and dns in names and
            any(lb["DNSName"] == dns and lb["VpcId"] == out["vpc_id"] and
                lb["CanonicalHostedZoneId"] == alias.get("HostedZoneId") for lb in lbs),
            "Existing demo DNS alias does not match this Ingress and VPC")
    return record


def backup(g, volumes, journal, save):
    for vol, claim in volumes.items():
        require(re.fullmatch(r"vol-[0-9a-f]+", vol), "Invalid EBS CSI volume ID")
        if vol not in journal["snapshots"]:
            tags = [{"Key": "Name", "Value": g.context + "-teardown"},
                    {"Key": "KubernetesClaim", "Value": claim}]
            snap = json.loads(g.aws("ec2", "create-snapshot", "--volume-id", vol, "--description",
                                    g.context + " teardown " + claim, "--tag-specifications",
                                    json.dumps([{"ResourceType": "snapshot", "Tags": tags}])))
            journal["snapshots"][vol] = snap["SnapshotId"]
            journal.setdefault("snapshot_sources", {})[snap["SnapshotId"]] = {
                "cluster": g.context, "region": g.env["AWS_REGION"], "claim": claim, "volume": vol,
            }
            save()
        print(f"{claim}: {vol} -> {journal['snapshots'][vol]}", flush=True)
    ids = list(journal["snapshots"].values())
    if ids:
        def completed():
            snaps = json.loads(g.aws("ec2", "describe-snapshots", "--snapshot-ids", *ids))["Snapshots"]
            require(all(s["State"] != "error" for s in snaps), "EBS snapshot failed; PVCs preserved")
            return len(snaps) == len(ids) and all(s["State"] == "completed" for s in snaps)
        g.until("all retained EBS snapshots to complete", completed)


def delete(g, *args):
    g.k("delete", *args, "--ignore-not-found", "--wait=true", f"--timeout={g.timeout}s")


def vpc_lbs(g, vpc):
    all_lbs = json.loads(g.aws("elbv2", "describe-load-balancers"))["LoadBalancers"]
    return [lb for lb in all_lbs if lb["VpcId"] == vpc]


def demo_lbs(g, vpc):
    ingress = g.obj("startup-apps", "ingress/demo-api")
    if ingress:
        annotations = ingress["metadata"].get("annotations", {})
        require(ingress["spec"].get("ingressClassName") == "alb" and
                not annotations.get("alb.ingress.kubernetes.io/group.name"),
                "Review nonstandard Ingress class or shared ALB group")
    owned = set()
    for lb in vpc_lbs(g, vpc):
        arn = lb["LoadBalancerArn"]
        try:
            tags = json.loads(g.aws("elbv2", "describe-tags", "--resource-arns", arn))["TagDescriptions"]
        except OpsError as error:
            # The controller may have finished between the inventory and tag reads.
            if "(LoadBalancerNotFound)" in str(error) and arn not in {item["LoadBalancerArn"] for item in vpc_lbs(g, vpc)}:
                continue
            raise
        labels = {t["Key"]: t["Value"] for row in tags if row["ResourceArn"] == arn for t in row["Tags"]}
        require(lb["Type"] == "application" and labels.get("elbv2.k8s.aws/cluster") == g.context and
                labels.get("ingress.k8s.aws/stack") == "startup-apps/demo-api",
                f"Review other load balancer in selected VPC before teardown: {arn} ({lb['DNSName']})")
        owned.add(arn)
    return owned


def release_ingress(g, vpc, expected):
    ingress = "ingress/demo-api"
    namespace = "startup-apps"
    g.k("-n", namespace, "delete", ingress, "--ignore-not-found", "--wait=false", "--request-timeout=30s")
    deadline = time.monotonic() + min(g.timeout, 600)
    next_report = 0
    while True:
        obj = g.obj(namespace, ingress)
        lbs = vpc_lbs(g, vpc)
        remaining = {lb["LoadBalancerArn"] for lb in lbs}
        require(not remaining - expected, "Unexpected new load balancer in selected VPC: " + ", ".join(sorted(remaining - expected)))
        if not obj and not lbs:
            print("Demo Ingress and ALB released.", flush=True)
            return
        now = time.monotonic()
        if now >= next_report or now >= deadline:
            meta = (obj or {}).get("metadata", {})
            controller = g.obj("kube-system", "deployment/aws-load-balancer-controller") or {}
            events = resources(g, "events", "-n", namespace, "--field-selector",
                               "involvedObject.kind=Ingress,involvedObject.name=demo-api,type=Warning")
            warnings = [e for e in events if not meta.get("uid") or e["involvedObject"].get("uid") == meta["uid"]]
            latest = max(warnings, key=lambda e: e.get("lastTimestamp") or e["metadata"].get("creationTimestamp", ""),
                         default={})
            print(f"Waiting for LB release: ingress={'present' if obj else 'absent'} "
                  f"deletionTimestamp={meta.get('deletionTimestamp')} finalizers={meta.get('finalizers', [])} "
                  f"controllerAvailable={controller.get('status', {}).get('availableReplicas', 0)} "
                  f"ALBs={sorted(remaining)} latestWarning={latest.get('message', '-')}", flush=True)
            next_report = now + 30
        if now >= deadline:
            raise OpsError("LB release timed out before Terraform apply. Inspect kube-system deployment/"
                           "aws-load-balancer-controller logs and startup-apps Ingress events, then retry.")
        time.sleep(5)


def release_external_secrets(g):
    ns = "startup-apps"
    kind = "externalsecrets.external-secrets.io"
    if not g.obj(ns, "namespace/" + ns) or not g.obj(ns, "crd/" + kind):
        return

    items = resources(g, kind, "-n", ns)
    if not items:
        return
    print("Releasing startup-apps ExternalSecrets while ESO and its RBAC are available", flush=True)
    g.k("delete", kind, "--all", "-n", ns, "--ignore-not-found", "--wait=false", "--request-timeout=30s")
    deadline = time.monotonic() + min(180, g.timeout)
    last = None
    while True:
        items = resources(g, kind, "-n", ns)
        if not items:
            print("startup-apps ExternalSecrets finalized", flush=True)
            return
        pending = sorted((i["metadata"]["name"], i["metadata"].get("finalizers", [])) for i in items)
        if pending != last:
            print(f"Pending startup-apps ExternalSecrets (name, finalizers): {pending}", flush=True)
            last = pending
        if time.monotonic() >= deadline:
            raise OpsError(f"ExternalSecret cleanup timed out: {pending}. Inspect the external-secrets "
                           "controller logs, startup-apps RBAC and namespace conditions, then retry destroy.")
        time.sleep(5)


def record_archive(g, out, journal, save):
    bucket = out.get("cnpg_backup_bucket_name")
    if not bucket or out.get("database_mode", "cnpg") == "none":
        return
    ns = "data-platform"
    kind = "clusters.postgresql.cnpg.io"
    if not g.obj(ns, "crd/" + kind):
        print("CNPG backup source unavailable: cluster CRD absent.")
        return
    cluster = g.obj(ns, kind + "/postgresql-baseline")
    if not cluster:
        print("CNPG backup source unavailable: database cluster absent.")
        return
    plugin = next((p for p in cluster["spec"].get("plugins", [])
                   if p["name"] == "barman-cloud.cloudnative-pg.io" and p.get("enabled", True)), {})
    params = plugin.get("parameters", {})
    store_name = params.get("barmanObjectName")
    store = None
    if store_name and g.obj(ns, "crd/objectstores.barmancloud.cnpg.io"):
        store = g.obj(ns, "objectstores.barmancloud.cnpg.io/" + store_name)
    destination = (store or {}).get("spec", {}).get("configuration", {}).get("destinationPath", "")
    if not destination.startswith("s3://" + bucket + "/"):
        print("CNPG backup source unavailable: no configured ObjectStore path in the selected backup bucket.")
        return
    source = {"cluster": g.context, "region": g.env["AWS_REGION"], "namespace": ns,
              "database_cluster": cluster["metadata"]["name"], "object_store": store_name,
              "server_name": params.get("serverName", cluster["metadata"]["name"]), "destination": destination}
    archives = journal.setdefault("cnpg_archives", [])
    if source not in archives:
        archives.append(source)
        save()
    print(f"CNPG backup source: {destination} (server {source['server_name']}); backup contents unverified.")


def remove_stack(g, out, journal, save, retain):
    expected_lbs = demo_lbs(g, out["vpc_id"])
    record = dns_record(g, out)
    controller = "statefulset/argocd-application-controller"
    if g.obj("argocd", controller):
        print("Suspending Argo CD reconciliation", flush=True)
        g.k("scale", "-n", "argocd", controller, "--replicas=0")
    g.until("Argo application-controller shutdown", lambda: not resources(
        g, "pods", "-n", "argocd", "-l", "app.kubernetes.io/name=argocd-application-controller"))
    current = storage(g)
    journal["volumes"] = sorted(set(journal.get("volumes", [])) | set(journal["snapshots"]) | set(current))
    save()
    if retain:
        record_archive(g, out, journal, save)
        backup(g, current, journal, save)
    if record:
        batch = {"Changes": [{"Action": "DELETE", "ResourceRecordSet": record}]}
        g.aws("route53", "change-resource-record-sets", "--hosted-zone-id", out["route53_hosted_zone_id"],
              "--change-batch", json.dumps(batch))
    release_ingress(g, out["vpc_id"], expected_lbs)
    release_external_secrets(g)
    require(set(storage(g)) <= set(current), "New persistent volume appeared; repeat the destroy preview")
    for ns, kind in [("data-platform", "scheduledbackups.postgresql.cnpg.io"),
                     ("data-platform", "clusters.postgresql.cnpg.io"),
                     ("observability", "prometheuses.monitoring.coreos.com"),
                     ("observability", "alertmanagers.monitoring.coreos.com")]:
        if g.obj(ns, "crd/" + kind):
            delete(g, kind, "--all", "-n", ns)
    # These namespaces belong to the dedicated personal AWS stack.
    require(set(storage(g)) <= set(current), "New persistent volume appeared; repeat the destroy preview")
    for ns in ("startup-apps", "data-platform", "observability"):
        delete(g, "namespace/" + ns)
    g.until("all cluster persistent volumes to be released", lambda: not resources(g, "pv"))
    for kind in ("nodepools.karpenter.sh", "nodeclaims.karpenter.sh", "ec2nodeclasses.karpenter.k8s.aws"):
        if g.obj("kube-system", "crd/" + kind):
            delete(g, kind, "--all")
    g.until("Karpenter-generated instance profiles to detach from the selected node role",
            lambda: not json.loads(g.aws("iam", "list-instance-profiles-for-role", "--role-name",
                                         out["karpenter_node_role_name"]))["InstanceProfiles"])

    def workers_gone():
        response = json.loads(g.aws("ec2", "describe-instances", "--filters",
                                    "Name=vpc-id,Values=" + out["vpc_id"], "Name=tag-key,Values=karpenter.sh/nodepool",
                                    "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down"))
        return not any(r["Instances"] for r in response["Reservations"])
    g.until("Karpenter EC2 workers to terminate", workers_gone)
    ids = journal["volumes"]
    if ids:
        g.until("identified source volumes to be deleted by CSI", lambda: not json.loads(g.aws(
            "ec2", "describe-volumes", "--filters", "Name=volume-id,Values=" + ",".join(ids)))["Volumes"])


def destroy(selected, env, config, confirm, retain=False):
    report, _ = inspect_infrastructure(selected, env, config, personal=True)
    name = report["cluster"]
    require(confirm in (None, name), "Destroy requires --confirm " + name)
    aws = env["aws"]
    settings = dict(os.environ, AWS_REGION=aws["region"], AWS_DEFAULT_REGION=aws["region"], AWS_PAGER="")
    if aws.get("profile"):
        settings["AWS_PROFILE"] = aws["profile"]
    # Teardown writes its own temporary connection only when the cluster exists.
    g = Cluster(name, settings, env.get("timeout", 1800), None)
    caller = json.loads(g.aws("sts", "get-caller-identity"))
    require(caller["Account"] == aws["expected_account_id"], "AWS caller account differs from inventory")
    if aws.get("role_arn"):
        role = aws["role_arn"].rsplit("/", 1)[-1]
        require(caller["Arn"].startswith(f"arn:aws:sts::{caller['Account']}:assumed-role/{role}/"),
                "Select credentials for the configured operator role")
    with lifecycle_lock(caller["Account"], aws["region"], name) as folder, tempfile.TemporaryDirectory(prefix="aws-destroy-") as tmp:
        tf = env["terraform"]
        tfenv = destroy_tfenv(g, tmp)
        source = ROOT / tf["root"]
        tfcmd = ["terraform", "-chdir=" + str(source)]
        initialize_backend(run, tfcmd, tfenv, source, tf["backend"], config.expanduser().resolve().parent)
        summary = check_selected_state(g, report, "destroy", pull=lambda: run(tfcmd + ["state", "pull"], tfenv))
        mode = summary.get("database_mode", "cnpg")
        print(f"Teardown database mode: {mode} ({'state' if 'database_mode' in summary else 'standard default'})", flush=True)
        session(g, env, config, confirm, folder, tmp, retain, database_mode=mode,
                legacy_addresses=summary.get("legacy_database_addresses", False),
                expected_state=(summary["lineage"], summary["serial"]), initialized=True)


def refresh_missing(terraform, tfcmd, tfenv, tmp, tf, base, mode, missing, keep, confirm, context, state_id):
    """Only persist refresh of the independently confirmed missing addresses."""
    print("Stale Terraform addresses (AWS absent):", *sorted(missing), sep="\n  ")
    if not confirm:
        print(f"Preview only. Repeat destroy with --confirm {context} to reconcile these state records.")
        return
    plan = tmp + "/refresh.tfplan"
    storage = sorted({original(a) for a in keep} & DURABLE)
    terraform("plan", "-refresh-only", "-input=false", "-lock-timeout=60s", "-out=" + plan,
              "-var-file=" + str(local_file(tf["variables_file"], base)),
              *database_variables(mode, {"database_storage": storage}), *["-target=" + a for a in sorted(missing)])
    document = json.loads(terraform("show", "-json", plan))
    drift = {r["address"] for r in document.get("resource_drift", []) if r["mode"] == "managed"
             and r["change"]["actions"] == ["delete"]}
    require(not any(document.get(k) for k in ("errored", "deferred_changes", "action_invocations"))
            and drift == missing and
            all(r["mode"] == "data" or (r["address"] in missing and r["change"]["actions"] == ["delete"])
                for r in document.get("resource_drift", [])) and
            all(r["mode"] == "data" or (r["change"]["actions"] == ["no-op"] and
                not r["change"].get("importing") and not r.get("previous_address"))
                for r in document.get("resource_changes", [])),
            "Refresh differs from the verified missing addresses; state preserved. Review the plan.")
    before = json.loads(terraform("state", "pull"))
    require((before["lineage"], before["serial"]) == state_id,
            "Selected state changed since storage inspection. Rerun destroy preview.")
    subprocess.run(tfcmd + ["apply", "-input=false", "-lock-timeout=60s", plan], env=tfenv, check=True)
    targets, remaining = partition(json.loads(terraform("state", "pull")))
    require(not targets and remaining == keep - missing, "Review state after refreshing absent database storage")
    print("State refreshed. Verified missing addresses removed; no AWS deletion requested.")


def destroy_tfenv(g, tmp):
    tfenv = dict(g.env, TF_DATA_DIR=tmp + "/tfdata", TF_WORKSPACE="default")
    require(not any(v for k, v in tfenv.items() if k.startswith("TF_CLI_ARGS")),
            "Unset TF_CLI_ARGS overrides before teardown")
    return {k: v for k, v in tfenv.items() if not k.startswith("TF_VAR_")}


def session(g, env, config, confirm, folder, tmp, retain=False, *, database_mode="cnpg", legacy_addresses=False, expected_state=None, initialized=False):
    tf = env["terraform"]
    tfenv = destroy_tfenv(g, tmp)
    source = ROOT / tf["root"]
    actual = source
    if legacy_addresses:
        # Targeted destroy acts on addresses as recorded. Applying move declarations
        # here would require targeting retained storage as well. Use the same backend
        # and inputs with a temporary configuration that omits only those moves.
        require(source.name in ("dev", "test"), "Unexpected legacy database layout")
        actual = Path(tmp) / "aws/environments" / source.name
        actual.mkdir(parents=True)
        (actual.parents[1] / "modules").symlink_to(source.parents[1] / "modules", target_is_directory=True)
        for file in source.iterdir():
            if file.name != "database-moves.tf" and file.name.endswith((".tf", ".tf.json", ".tfvars", ".tfvars.json")):
                (actual / file.name).symlink_to(file)
        lock = source / ".terraform.lock.hcl"
        if lock.is_file():
            shutil.copyfile(lock, actual / lock.name)
    tfcmd = ["terraform", "-chdir=" + str(actual)]
    def terraform(*args):
        return run(tfcmd + list(args), tfenv)
    base = config.expanduser().resolve().parent
    if not initialized or legacy_addresses:
        initialize_backend(run, tfcmd, tfenv, actual, tf["backend"], base)
    state = json.loads(terraform("state", "pull"))
    require(re.fullmatch(r"[0-9a-fA-F-]{36}", state.get("lineage", "")), "Invalid Terraform state lineage")
    receipt = folder / (state["lineage"] + ".json")
    journal = json.loads(receipt.read_text()) if receipt.exists() else {}
    out = {k: v["value"] for k, v in state.get("outputs", {}).items()}
    if expected_state:
        require((state["lineage"], state["serial"]) == expected_state,
                "Selected state changed since destroy preflight. Rerun destroy preview.")
    live_names = json.loads(g.aws("eks", "list-clusters"))["clusters"]
    vpc = out.get("vpc_id") or journal.get("vpc")
    if journal.get("vpc") != vpc or not journal:
        previous = set(journal.get("prior_snapshots", [])) | set(journal.get("snapshots", {}).values())
        journal = {"vpc": vpc, "prior_snapshots": sorted(previous), "snapshots": {}, "cleaned": False,
                   "snapshot_sources": journal.get("snapshot_sources", {}), "cnpg_archives": journal.get("cnpg_archives", [])}
    owner = creation_plan(state)
    if owner is None and journal.get("cleaned") and g.context not in live_names:
        owner = journal.get("owner")
    if journal.get("complete") and g.context not in live_names:
        retain = journal.get("retain", retain)
    targets, keep = partition(state, owner, retain)
    if targets and journal.get("cleaned") and "retain" in journal:
        require(retain == journal["retain"], "Resume the pending Terraform apply with the previous backup policy")
    recorded = sorted(set(journal.get("prior_snapshots", [])) | set(journal["snapshots"].values()))
    print("Recorded snapshot IDs (historical; AWS existence not checked):", recorded)
    missing = report_storage(g, env["aws"], state, targets, keep, owner, retain)
    if not targets:
        require(g.context not in live_names, "EKS exists but selected state has no teardown targets")
        if journal.get("vpc"):
            check_absent(g, journal["vpc"])
        print(f"No AWS deletion targets for {g.context}. Shared Terraform backend retained.")
        if journal.get("pending_data_deletions"):
            verify_deleted_storage(g, env["aws"], journal)
            if confirm:
                journal["complete"] = True
                journal.pop("pending_data_deletions")
                atomic_write(receipt, json.dumps(journal, indent=2))
        if receipt.is_file():
            print("Local teardown receipt:", receipt)
        if missing:
            refresh_missing(terraform, tfcmd, tfenv, tmp, tf, base, database_mode,
                            missing, keep, confirm, g.context, (state["lineage"], state["serial"]))
        return
    require(vpc and (out.get("eks_cluster_name") == g.context or journal.get("cleaned")),
            "Cannot establish selected state ownership")
    def save():
        atomic_write(receipt, json.dumps(journal, indent=2))
    if g.context in live_names:
        live = json.loads(g.aws("eks", "describe-cluster", "--name", g.context))["cluster"]
        require(live.get("arn") == f"arn:aws:eks:{env['aws']['region']}:{env['aws']['expected_account_id']}:cluster/{g.context}",
                "Unexpected EKS cluster ARN")
        require(live["resourcesVpcConfig"]["vpcId"] == vpc and
                live["endpoint"] == (out.get("eks_cluster_endpoint") or journal.get("endpoint")),
                "EKS endpoint or VPC differs from selected state")
        if journal.get("endpoint"):
            require(journal["endpoint"] == live["endpoint"], "Cluster changed during teardown")
        journal["endpoint"] = live["endpoint"]
        cluster_sg = live["resourcesVpcConfig"].get("clusterSecurityGroupId")
        if cluster_sg:
            require(journal.get("cluster_sg", cluster_sg) == cluster_sg, "Cluster security group changed")
            journal["cluster_sg"] = cluster_sg
        require(not owner or generation({"tags": live.get("tags")}) == owner, "Live EKS creation marker differs from state")
        if not journal["cleaned"]:
            g.path = Path(tmp) / "kubeconfig"
            run(["aws", "eks", "update-kubeconfig", "--name", g.context, "--alias", g.context,
                 "--kubeconfig", str(g.path)], g.env)
            if journal["snapshots"]:
                controller = g.obj("argocd", "statefulset/argocd-application-controller") or {}
                if controller.get("spec", {}).get("replicas", 1) > 0:
                    reopen_receipt(journal)
            volumes = storage(g)
            print("Will delete PVC volumes:", volumes)
            print("Will create EBS snapshots for:", sorted(volumes.keys() - journal["snapshots"].keys()) if retain else [])
            print("ALBs to release:", sorted(demo_lbs(g, vpc)))
            print("Demo DNS alias:", (dns_record(g, out) or {}).get("Name", "absent"))
    else:
        require(journal.get("cleaned"), "EKS absent before Kubernetes cleanup could be verified")
    plan = tmp + "/destroy.tfplan"

    database_storage = sorted({original(a) for a in targets | keep} & DURABLE)
    variables = database_variables(database_mode, {"database_storage": database_storage})
    def review(addresses):
        terraform("plan", "-destroy", "-input=false", "-lock-timeout=60s", "-out=" + plan,
                  "-var-file=" + str(local_file(tf["variables_file"], base)), *variables,
                  *["-target=" + a for a in sorted(addresses)])
        return check_plan(json.loads(terraform("show", "-json", plan)), addresses, owner)

    def apply():
        subprocess.run(tfcmd + ["apply", "-input=false", "-lock-timeout=60s", plan], env=tfenv, check=True)

    deletes = review(targets)
    if any(a.startswith("module.vpc.") for a in targets):
        print(f"After EKS deletion, inspect {vpc} for detached CNI ENIs and release "
              f"the recorded EKS security group {journal.get('cluster_sg', '(unrecorded)')} if verified.")
    print("Terraform destroy:", *deletes, sep="\n  ")
    print("Shared state backend, its KMS key and separate runtime identity root are outside this plan.")
    if keep - missing:
        print("Protected data addresses:", *sorted(keep - missing), sep="\n  ")
    if missing:
        print("Stale state addresses (AWS absent):", *sorted(missing), sep="\n  ")
    if confirm is None:
        print("Preview complete. Execute the same command with --confirm " + g.context)
        return
    pending = journal.setdefault("pending_data_deletions", {})
    for row in state["resources"]:
        address = ".".join((row.get("module", ""), row["type"], row["name"]))
        if row["mode"] == "managed" and address in targets and original(address) in (BUCKET, SECRET):
            pending[original(address)] = row["instances"][0]["attributes"].get("arn")
    if not journal["cleaned"]:
        journal.update(owner=owner, retain=retain)
        save()
        remove_stack(g, out, journal, save, retain)
        journal["cleaned"] = True
        save()
    save()
    network = {a for a in targets if a.startswith("module.vpc.")}
    services = targets - network
    if services:
        if network:
            review(services)
        print("Applying service destroy plan", flush=True)
        apply()
    if network:
        current = json.loads(terraform("state", "pull"))
        require(current.get("lineage") == state["lineage"], "Terraform state lineage changed")
        remaining, retained = partition(current, owner, retain)
        require(remaining <= network and keep - missing <= retained <= keep, "Review changed state before network cleanup")
        vpc_ids = [i["attributes"]["id"] for r in current["resources"] if r.get("module") == "module.vpc"
                   and r["mode"] == "managed" and r["type"] == "aws_vpc" for i in r["instances"]]
        if vpc_ids:
            require(vpc_ids == [vpc], "VPC in remaining state differs from receipt")
            release_network(g, journal, current)
        else:
            # A previous partial apply can leave independent network resources such as an EIP.
            check_absent(g, vpc)
        if remaining:
            review(remaining)
            print("Applying network destroy plan", flush=True)
            apply()
    remaining, retained = partition(json.loads(terraform("state", "pull")), owner, retain)
    require(not remaining and keep - missing <= retained <= keep, "Review residual or changed Terraform state")
    check_absent(g, vpc)
    report_storage(g, env["aws"], state, set(), retained, owner, retain)
    verify_deleted_storage(g, env["aws"], journal)
    journal.pop("pending_data_deletions", None)
    journal["complete"] = True
    save()
    print(f"AWS teardown complete for {g.context}. EKS and VPC absent.")
    print("Local teardown receipt:", receipt)


def verify_deleted_storage(g, aws, journal):
    for kind, arn in journal.get("pending_data_deletions", {}).items():
        require(kind in (BUCKET, SECRET), "Unexpected database entry in teardown receipt")
        live = observe(g, kind, aws["expected_account_id"], aws["region"], expected_arn=arn)
        require(live.status != "present", f"Cleanup incomplete: {live.name} still exists in AWS.")
        print(f"AWS {live.status}: {live.name}" + (f" on {live.deletion_date}" if live.deletion_date else ""))


def check_absent(g, vpc):
    require(g.context not in json.loads(g.aws("eks", "list-clusters"))["clusters"], "EKS still exists")
    require(not json.loads(g.aws("ec2", "describe-vpcs", "--filters", "Name=vpc-id,Values=" + vpc))["Vpcs"],
            "Selected VPC still exists")
