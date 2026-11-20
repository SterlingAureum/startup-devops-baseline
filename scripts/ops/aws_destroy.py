"""Teardown of the standard personal dev stack. Keep durable data in its original state."""
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

from aws_deploy import Cluster, run
from aws_preflight import inspect, local_file
from configuration import ROOT, require
from connections import atomic_write

PHASES = ["inspect selected account, backend, Terraform delete plan and live dev identity",
          "pause GitOps and snapshot dev persistent volumes", "release exact DNS alias and ingress",
          "release workloads, PVCs and Karpenter nodes while controllers are available",
          "apply reviewed Terraform plan and check remaining state, VPC and cluster"]
MODULES = {"eks", "vpc", "github_actions_runtime_identity", "cnpg_backup", "external_secrets",
           "tls_dns", "fis", "karpenter"}


def partition(state):
    destroy, keep = set(), set()
    for r in state.get("resources", []):
        if r["mode"] != "managed":
            continue
        module = r.get("module", "")
        require(module.startswith("module.") and module.split(".")[1].split("[")[0] in MODULES,
                "Unexpected managed resource outside the standard dev modules: " + module)
        if module.startswith("module.github_actions_runtime_identity"):
            require(r["type"] == "aws_eks_access_entry", "Review unexpected persistent identity in dev state")
        addr = ".".join([module, r["type"], r["name"]])
        retained = ((module == "module.cnpg_backup" and r["type"].startswith("aws_s3_bucket"))
                    or addr == "module.external_secrets.aws_secretsmanager_secret.this")
        for instance in r["instances"]:
            suffix = "[" + json.dumps(instance["index_key"], ensure_ascii=False) + "]" if "index_key" in instance else ""
            (keep if retained else destroy).add(addr + suffix)
    return destroy, keep


def check_plan(plan, targets):
    deletes = set()
    for change in plan.get("resource_changes", []):
        actions = change["change"]["actions"]
        if change["mode"] == "data" or actions == ["no-op"]:
            continue
        require(actions == ["delete"] and change["address"] in targets,
                f"Unexpected destroy plan action: {change['address']} {actions}")
        deletes.add(change["address"])
    # Drifted resources already gone in AWS need no delete action.
    gone = {c["address"] for c in plan.get("resource_drift", []) if c["change"]["actions"] == ["delete"]}
    require(targets <= deletes | gone, "Terraform omitted managed dev objects from the destroy plan")
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
            "Existing demo DNS alias does not match this dev Ingress and VPC")
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


def remove_stack(g, out, journal, save):
    record = dns_record(g, out)
    print("Suspending Argo CD reconciliation", flush=True)
    g.k("scale", "-n", "argocd", "statefulset/argocd-application-controller", "--replicas=0")
    g.until("Argo application-controller shutdown", lambda: not resources(
        g, "pods", "-n", "argocd", "-l", "app.kubernetes.io/name=argocd-application-controller"))
    backup(g, storage(g), journal, save)
    if record:
        batch = {"Changes": [{"Action": "DELETE", "ResourceRecordSet": record}]}
        g.aws("route53", "change-resource-record-sets", "--hosted-zone-id", out["route53_hosted_zone_id"],
              "--change-batch", json.dumps(batch))
    delete(g, "ingress/demo-api", "-n", "startup-apps")
    g.until("load balancers in the dedicated dev VPC to disappear", lambda: not any(
        lb["VpcId"] == out["vpc_id"] for lb in json.loads(g.aws("elbv2", "describe-load-balancers"))["LoadBalancers"]))
    require(set(storage(g)) <= set(journal["snapshots"]), "New persistent volume appeared; rerun to snapshot it")
    for ns, kind in [("data-platform", "scheduledbackups.postgresql.cnpg.io"),
                     ("data-platform", "clusters.postgresql.cnpg.io"),
                     ("observability", "prometheuses.monitoring.coreos.com"),
                     ("observability", "alertmanagers.monitoring.coreos.com")]:
        if g.obj(ns, "crd/" + kind):
            delete(g, kind, "--all", "-n", ns)
    # These namespaces belong to the dedicated personal dev stack.
    require(set(storage(g)) <= set(journal["snapshots"]), "New persistent volume appeared; rerun to snapshot it")
    for ns in ("startup-apps", "data-platform", "observability"):
        delete(g, "namespace/" + ns)
    g.until("all dev persistent volumes to be released", lambda: not resources(g, "pv"))
    for kind in ("nodepools.karpenter.sh", "nodeclaims.karpenter.sh", "ec2nodeclasses.karpenter.k8s.aws"):
        if g.obj("kube-system", "crd/" + kind):
            delete(g, kind, "--all")
    g.until("Karpenter-generated instance profiles to detach from the dev node role",
            lambda: not json.loads(g.aws("iam", "list-instance-profiles-for-role", "--role-name",
                                         out["karpenter_node_role_name"]))["InstanceProfiles"])

    def workers_gone():
        response = json.loads(g.aws("ec2", "describe-instances", "--filters",
                                    "Name=vpc-id,Values=" + out["vpc_id"], "Name=tag-key,Values=karpenter.sh/nodepool",
                                    "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down"))
        return not any(r["Instances"] for r in response["Reservations"])
    g.until("Karpenter EC2 workers to terminate", workers_gone)
    ids = list(journal["snapshots"])
    if ids:
        g.until("snapshotted source volumes to be deleted by CSI", lambda: not json.loads(g.aws(
            "ec2", "describe-volumes", "--filters", "Name=volume-id,Values=" + ",".join(ids)))["Volumes"])


def destroy(env, config, confirm):
    report = inspect("aws-dev", env, config, personal=True)
    name = report["cluster"]
    require(confirm in (None, name), "Destroy requires --confirm " + name)
    aws = env["aws"]
    settings = dict(os.environ, AWS_REGION=aws["region"], AWS_DEFAULT_REGION=aws["region"], AWS_PAGER="")
    if aws.get("profile"):
        settings["AWS_PROFILE"] = aws["profile"]
    g = Cluster(name, settings, env.get("timeout", 1800))
    caller = json.loads(g.aws("sts", "get-caller-identity"))
    require(caller["Account"] == aws["expected_account_id"], "AWS caller account differs from inventory")
    if aws.get("role_arn"):
        role = aws["role_arn"].rsplit("/", 1)[-1]
        require(caller["Arn"].startswith(f"arn:aws:sts::{caller['Account']}:assumed-role/{role}/"),
                "Select credentials for the configured operator role")
    folder = Path.home() / ".local/state/startup-devops-baseline" / caller["Account"] / aws["region"] / name
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (folder / "destroy.lock").open("a") as lock, tempfile.TemporaryDirectory(prefix="aws-dev-destroy-") as tmp:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        session(g, env, config, confirm, folder, tmp)


def session(g, env, config, confirm, folder, tmp):
    tf = env["terraform"]
    tfenv = dict(g.env, TF_DATA_DIR=tmp + "/tfdata", TF_WORKSPACE="default")
    tfcmd = ["terraform", "-chdir=" + str(ROOT / tf["root"])]
    def terraform(*args):
        return run(tfcmd + list(args), tfenv)
    base = config.expanduser().resolve().parent
    # Environment-supplied Terraform CLI arguments can silently change the reviewed plan.
    require(not any(v for k, v in tfenv.items() if k.startswith("TF_CLI_ARGS")),
            "Unset TF_CLI_ARGS overrides before dev teardown")
    terraform("init", "-input=false", "-backend-config=" + str(local_file(tf["backend_file"], base)))
    state = json.loads(terraform("state", "pull"))
    targets, keep = partition(state)
    require(re.fullmatch(r"[0-9a-fA-F-]{36}", state.get("lineage", "")), "Invalid dev state lineage")
    receipt = folder / (state["lineage"] + ".json")
    journal = json.loads(receipt.read_text()) if receipt.exists() else {}
    out = {k: v["value"] for k, v in state.get("outputs", {}).items()}
    live_names = json.loads(g.aws("eks", "list-clusters"))["clusters"]
    if not targets:
        require(g.context not in live_names, "EKS exists but dev state has no teardown targets")
        if journal.get("vpc"):
            check_absent(g, journal["vpc"])
        print("No dev teardown targets. Retained state addresses:", *sorted(keep), sep="\n")
        return
    vpc = out.get("vpc_id") or journal.get("vpc")
    require(vpc and (out.get("eks_cluster_name") == g.context or journal.get("cleaned")),
            "Cannot establish dev state ownership")
    if journal.get("vpc") != vpc:
        journal = {"vpc": vpc, "snapshots": {}, "cleaned": False}
    def save():
        atomic_write(receipt, json.dumps(journal, indent=2))
    if g.context in live_names:
        live = json.loads(g.aws("eks", "describe-cluster", "--name", g.context))["cluster"]
        require(live.get("arn") == f"arn:aws:eks:{env['aws']['region']}:{env['aws']['expected_account_id']}:cluster/{g.context}",
                "Unexpected EKS cluster ARN")
        require(live["resourcesVpcConfig"]["vpcId"] == vpc and
                live["endpoint"] == (out.get("eks_cluster_endpoint") or journal.get("endpoint")),
                "EKS endpoint or VPC differs from selected dev state")
        if journal.get("endpoint"):
            require(journal["endpoint"] == live["endpoint"], "Cluster changed during teardown")
        journal["endpoint"] = live["endpoint"]
        if not journal["cleaned"]:
            g.path = Path(tmp) / "kubeconfig"
            run(["aws", "eks", "update-kubeconfig", "--name", g.context, "--alias", g.context,
                 "--kubeconfig", str(g.path)], g.env)
            print("Volumes to snapshot:", storage(g))
            print("Demo DNS alias:", (dns_record(g, out) or {}).get("Name", "absent"))
    else:
        require(journal.get("cleaned"), "EKS absent before Kubernetes cleanup could be verified")
    plan = tmp + "/destroy.tfplan"
    terraform("plan", "-destroy", "-input=false", "-lock-timeout=60s", "-out=" + plan,
              "-var-file=" + str(local_file(tf["variables_file"], base)),
              *["-target=" + a for a in sorted(targets)])
    deletes = check_plan(json.loads(terraform("show", "-json", plan)), targets)
    print("Terraform destroy:", *deletes, sep="\n  ")
    print("Retain in dev state:", *sorted(keep), sep="\n  ")
    if confirm is None:
        print("Preview complete. Execute the same command with --confirm " + g.context)
        return
    if not journal["cleaned"]:
        save()
        remove_stack(g, out, journal, save)
        journal["cleaned"] = True
        save()
    print("Applying dev destroy plan", flush=True)
    subprocess.run(tfcmd + ["apply", "-input=false", "-lock-timeout=60s", plan], env=tfenv, check=True)
    remaining, retained = partition(json.loads(terraform("state", "pull")))
    require(not remaining and retained == keep, "Review residual or changed Terraform state")
    check_absent(g, vpc)
    print("AWS dev teardown complete. EKS and VPC absent. Retained snapshots:", journal["snapshots"])
    print("Local teardown receipt:", receipt)


def check_absent(g, vpc):
    require(g.context not in json.loads(g.aws("eks", "list-clusters"))["clusters"], "EKS still exists")
    require(not json.loads(g.aws("ec2", "describe-vpcs", "--filters", "Name=vpc-id,Values=" + vpc))["Vpcs"],
            "Dev VPC still exists")
