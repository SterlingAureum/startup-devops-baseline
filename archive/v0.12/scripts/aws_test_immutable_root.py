"""Pinned Root rendering, private evidence and whole-session budget helpers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "delivery/contracts/v0.11.9.3.6.7.5.2-aws-test-immutable-root-deployment.json"
spec = importlib.util.spec_from_file_location("cost_predecessor", ROOT / "scripts/review-v0.11.9.3.6.7.5.1-aws-test-root-cost.py")
cost_predecessor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cost_predecessor)
p = cost_predecessor.prior
CONFIRMATIONS = {
    "CONFIRM_AWS_TEST_ROOT_DEPLOYMENT": "deploy-reviewed-aws-test-root-once",
    "CONFIRM_AWS_TEST_CREDENTIAL_SEED": "seed-reviewed-aws-test-cnpg-credential-once",
    "CONFIRM_AWS_TEST_DNS_UPSERT": "upsert-reviewed-aws-test-demo-alias-once"}


def source_checks(root=ROOT):
    cost_predecessor.source_checks(root)
    c = p.load(root / CONTRACT)
    for item in c["reviewedFiles"]:
        p.require(p.digest(root / item["path"]) == item["sha256"], "predecessor-drift")
    return c


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_private(path):
    p.private(path)
    p.private(path.parent, 0o700)
    p.persistent(path)
    return p.load(path)


def new_directory(path):
    p.private(path.parent, 0o700)
    p.persistent(path)
    p.require(not path.exists() and not path.is_symlink(), "new-directory-required")
    path.mkdir(mode=0o700)


def budget(c, at):
    b = c["budget"]
    start, end = p.utc(b["accountingStartUtc"]), p.utc(b["cleanupCompleteByUtc"])
    stop = end - timedelta(seconds=b["cleanupReserveSeconds"])
    p.require(start <= at and at + timedelta(seconds=b["minimumDeploymentSeconds"]) <= stop,
              "insufficient-time-before-cleanup-reserve")
    rates = c["costEnvelope"]
    idle = sum((p.amount(v) for v in rates["idleHourlyUsd"].values()), Decimal(0))
    peak = sum((p.amount(v) for v in rates["peakHourlyUsd"].values()), Decimal(0))
    value = idle * Decimal(str((at - start).total_seconds())) / 3600
    value += peak * Decimal(str((end - at).total_seconds())) / 3600
    value += p.amount(rates["fixedReserveUsd"])
    p.require(value <= p.amount(b["totalLimitUsd"]), "whole-session-estimate-exceeds-budget")
    return {"estimated_total_usd": str(value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)),
            "total_budget_limit_usd": b["totalLimitUsd"], "expected_spend_target_usd": b["expectedSpendTargetUsd"],
            "historical_billed_spend_usd": None, "accounting_start_utc": b["accountingStartUtc"],
            "cleanup_complete_by_utc": b["cleanupCompleteByUtc"],
            "mutation_stop_utc": stop.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "estimate_is_billing_guarantee": False}


def assert_confirmations(environment, execute):
    for key, value in CONFIRMATIONS.items():
        p.require(environment.get(key) == value if execute else key not in environment,
                  "separate-root-credential-dns-confirmations-required")
    forbidden = ("CONFIRM_AWS_TEST_APPLY", "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_ENVIRONMENT_DESTROY",
                 "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION", "CONFIRM_AWS_TEST_GITOPS_EXECUTION")
    p.require(not any(environment.get(k) for k in forbidden), "unrelated-execution-confirmation")
    p.require(not any(k.startswith("AWS_ENDPOINT_URL") for k in environment), "custom-aws-endpoint")


def validate_outputs(outputs, account):
    for key in ("cnpg_backup_role_arn", "external_secrets_role_arn", "external_secrets_secret_arn"):
        p.require(re.fullmatch(r"arn:aws:[^:]+:[^:]*:" + re.escape(account) + r":.+", outputs[key]),
                  "state-arn-account")
    p.require(re.fullmatch(r"vpc-[0-9a-f]+", outputs["vpc_id"]), "vpc-format")
    p.require(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", outputs["cnpg_backup_bucket_name"]),
              "bucket-format")
    p.require(outputs["external_secrets_secret_name"] == "startup-devops-baseline-test/demo-api/postgresql",
              "test-container-name")


def patch(target, operations):
    return {"target": target, "patch": json.dumps(operations)}


def object_patch(api, kind, name, spec):
    return {"target": {"group": api.split("/")[0], "version": api.split("/")[1],
                       "kind": kind, "name": name},
            "patch": yaml.safe_dump({"apiVersion": api, "kind": kind,
                                      "metadata": {"name": name}, "spec": spec}, sort_keys=False)}


def child_source(item, commit, outputs):
    source = copy.deepcopy(item["source"])
    name = item["name"]
    if source["repoURL"] == p.REPO:
        source["targetRevision"] = commit
    if name == p.ALB:
        source["helm"]["valuesObject"]["vpcId"] = outputs["vpc_id"]
    if name == "postgresql-baseline":
        source["kustomize"] = {"patches": [
            object_patch("barmancloud.cnpg.io/v1", "ObjectStore", "postgresql-baseline-backup",
                         {"configuration": {"destinationPath": "s3://" + outputs["cnpg_backup_bucket_name"] + "/postgresql-baseline"}}),
            object_patch("postgresql.cnpg.io/v1", "Cluster", "postgresql-baseline",
                         {"serviceAccountTemplate": {"metadata": {"annotations": {
                             "eks.amazonaws.com/role-arn": outputs["cnpg_backup_role_arn"]}}}})]}
    return source


def root_patches(c, commit, outputs):
    patches = []
    for item in c["applications"]:
        source = child_source(item, commit, outputs)
        if source != item["source"]:
            patches.append(patch({"group": "argoproj.io", "version": "v1alpha1", "kind": "Application",
                                  "name": item["name"]}, [{"op": "replace", "path": "/spec/source", "value": source}]))
    for name in c["capacity"]["removedNodePools"]:
        patches.append({"target": {"group": "karpenter.sh", "version": "v1", "kind": "NodePool", "name": name},
                        "patch": yaml.safe_dump({"apiVersion": "karpenter.sh/v1", "kind": "NodePool",
                                                "metadata": {"name": name}, "$patch": "delete"})})
    for name in ("database-ondemand", "application-ondemand"):
        template = yaml.safe_load((ROOT / next(x["path"] for x in
            p.load(ROOT / cost_predecessor.CONTRACT)["nodePools"] if x["name"] == name)).read_text())
        requirements = template["spec"]["template"]["spec"]["requirements"]
        requirements = [r for r in requirements if r["key"] != "karpenter.sh/capacity-type"]
        requirements += [{"key": "node.kubernetes.io/instance-type", "operator": "In", "values": ["c6i.large"]},
                         {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["on-demand"]}]
        patches.append(patch({"group": "karpenter.sh", "version": "v1", "kind": "NodePool", "name": name},
                             [{"op": "replace", "path": "/spec/template/spec/requirements", "value": requirements}]))
    return patches


def build(directory):
    r = subprocess.run(["kubectl", "kustomize", str(directory)], capture_output=True, timeout=120)
    p.require(r.returncode == 0, "kustomize-build-failed")
    return list(yaml.safe_load_all(r.stdout))


def validate_render(items, c, commit, outputs):
    apps = {o["metadata"]["name"]: o for o in items if o["kind"] == "Application"}
    p.require(len(items) == 23 and len(apps) == len(c["applications"]), "render-resource-count")
    p.require(set(apps) == {x["name"] for x in c["applications"]}, "render-application-inventory")
    for item in c["applications"]:
        app = apps[item["name"]]
        p.require(app["spec"]["source"] == child_source(item, commit, outputs), "render-source-drift")
        p.require(app["spec"]["destination"]["server"] == "https://kubernetes.default.svc", "destination-cluster")
    pools = [o for o in items if o["kind"] == "NodePool"]
    p.require({x["metadata"]["name"] for x in pools} == {"database-ondemand", "application-ondemand"},
              "render-pool-scope")
    for pool in pools:
        req = {r["key"]: r for r in pool["spec"]["template"]["spec"]["requirements"]}
        p.require(req["node.kubernetes.io/instance-type"]["values"] == ["c6i.large"] and
                  req["karpenter.sh/capacity-type"]["values"] == ["on-demand"], "render-instance-scope")


def render_bundle(c, commit, outputs, work, builder=build):
    p.require(re.fullmatch(r"[0-9a-f]{40}", commit), "commit-format")
    source = work / "source"
    source.mkdir(mode=0o700)
    shutil.copytree(ROOT / "clusters", source / "clusters")
    directory = source / "clusters/aws/overlays/test"
    kfile = directory / "kustomization.yaml"
    kustomization = yaml.safe_load(kfile.read_text())
    patches = root_patches(c, commit, outputs)
    kustomization["patches"].extend(patches)
    kfile.write_text(yaml.safe_dump(kustomization, sort_keys=False))
    items = builder(directory)
    validate_render(items, c, commit, outputs)
    pg_directory = source / "clusters/aws/overlays/test/data-platform/postgresql"
    pg_file = pg_directory / "kustomization.yaml"
    pg_config = yaml.safe_load(pg_file.read_text())
    pg_source = child_source(next(a for a in c["applications"] if a["name"] == "postgresql-baseline"), commit, outputs)
    pg_config.setdefault("patches", []).extend(pg_source["kustomize"]["patches"])
    pg_file.write_text(yaml.safe_dump(pg_config, sort_keys=False))
    pg_items = builder(pg_directory)
    cluster = next(o for o in pg_items if o["kind"] == "Cluster")
    store = next(o for o in pg_items if o["kind"] == "ObjectStore")
    p.require(cluster["spec"]["instances"] == 3 and cluster["spec"]["storage"]["size"] == "20Gi" and
              cluster["spec"]["serviceAccountTemplate"]["metadata"]["annotations"]["eks.amazonaws.com/role-arn"] ==
              outputs["cnpg_backup_role_arn"], "nested-cnpg-render")
    p.require(store["spec"]["configuration"]["destinationPath"] == "s3://" + outputs["cnpg_backup_bucket_name"] + "/postgresql-baseline",
              "nested-backup-render")
    root = yaml.safe_load((ROOT / "clusters/aws/overlays/test/root-app.yaml").read_text())
    root["spec"]["source"].update(targetRevision=commit, kustomize={"patches": patches})
    p.write(work / "root-application.json", root)
    p.write(work / "rendered-root-resources.json", {"items": items})
    source_map = [{"name": x["metadata"]["name"], "source": x["spec"]["source"],
                   "destination": x["spec"]["destination"]} for x in items if x["kind"] == "Application"]
    p.write(work / "application-source-map.json", source_map)
    p.write(work / "rendered-postgresql-resources.json", {"items": pg_items})
    return root, items


def validate_bundle(bundle, inputs_path, expected, c):
    p.private(bundle, 0o700)
    p.persistent(bundle)
    plan = read_private(bundle / "private-root-plan.json")
    p.require(plan["expected_main"] == expected and plan["inputs_sha256"] == p.digest(inputs_path), "plan-input-binding")
    for filename, key in (("root-application.json", "root_manifest_sha256"),
                          ("rendered-root-resources.json", "render_sha256"),
                          ("rendered-postgresql-resources.json", "postgresql_render_sha256"),
                          ("application-source-map.json", "source_map_sha256")):
        read_private(bundle / filename)
        p.require(p.digest(bundle / filename) == plan[key], "private-render-byte-drift")
    p.require(plan["contract_sha256"] == p.digest(ROOT / CONTRACT), "contract-binding")
    p.require(plan["human_manifest_reviewed"] is True and plan["human_cost_scope_reviewed"] is True,
              "human-private-manifest-and-cost-review-required")
    p.require(plan["cleanup_complete_by_utc"] == c["budget"]["cleanupCompleteByUtc"] and
              plan["total_budget_limit_usd"] == "36.00", "budget-window-binding")
    age = (now() - p.utc(plan["created_at_utc"])).total_seconds()
    p.require(0 <= age <= 3600, "private-plan-review-expired")
    return plan
