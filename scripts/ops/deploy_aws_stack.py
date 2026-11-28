"""Deploy the standard AWS GitOps stack from terraform output -json on stdin."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from aws_deploy import apply_outputs, lifecycle_lock, operator_cluster
from aws_preflight import kustomize
from configuration import (ROOT, OpsError, delivery_target, environment, load_yaml,
                           personal_inventory, require, standard_aws_target)


def deploy_outputs(config, name, stream, adopt=None):
    env = environment(config, name)
    require(env["driver"] == "aws" and env["argocd"]["namespace"] == "argocd",
            "Select a standard AWS inventory entry with the argocd namespace")
    catalog, manifest = delivery_target(env)
    target = standard_aws_target(name, env, catalog, manifest)
    require(target, "Select a standard AWS dev or test target")
    obj = json.load(stream)
    require(isinstance(obj, dict) and all(isinstance(entry, dict) and "value" in entry for entry in obj.values()),
            "Expected terraform output -json on stdin")
    out = {key: entry["value"] for key, entry in obj.items()}
    mode = env.get("database", {}).get("mode", "cnpg")
    required = {"environment_name", "eks_cluster_name", "eks_cluster_endpoint", "vpc_id", "demo_api_hostname",
                "route53_hosted_zone_id", "aws_load_balancer_controller_role_arn", "karpenter_controller_role_arn"}
    if mode == "cnpg":
        required.update(("external_secrets_role_arn", "external_secrets_secret_arn", "external_secrets_secret_name",
                         "cnpg_backup_role_arn", "cnpg_backup_bucket_name"))
    require(all(isinstance(out.get(key), str) and out[key] for key in required), "Missing required stack outputs")
    require(adopt is None or (mode == "cnpg" and re.fullmatch(r"[A-Za-z0-9-]{32,64}", adopt)),
            "Credential adoption requires CNPG and an exact version ID")
    root = load_yaml((ROOT / manifest).read_text())
    source = root["spec"]["source"]
    if "gitops" in env:
        git = env["gitops"]
        require(git["repository"] == source["repoURL"] and git["root_application"] == root["metadata"]["name"]
                and git.get("revision") in (None, source["targetRevision"]) and not git.get("parameters"),
                "Inventory GitOps settings differ from the selected AWS root")
    apps = {doc["metadata"]["name"]: doc for doc in kustomize(source["path"]) if doc and doc["kind"] == "Application"}
    alb = apps["aws-load-balancer-controller"]["spec"]["source"]["helm"]["valuesObject"]
    aws = env["aws"]
    require(out["eks_cluster_name"] == alb["clusterName"] and aws["region"] == alb["region"] and
            out["demo_api_hostname"] == urlsplit(catalog["environments"][target.delivery_environment]["url"]).hostname,
            "Terraform outputs differ from the selected overlay cluster, region or hostname")
    g = operator_cluster(env, alb["clusterName"])
    report = {"stage": target.stage, "gitops_root": manifest, "database_mode": mode}
    with lifecycle_lock(aws["expected_account_id"], aws["region"], g.context) as folder:
        with tempfile.TemporaryDirectory(prefix="aws-stack-") as tmp:
            apply_outputs(g, report, env, out, folder, Path(tmp), adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=personal_inventory())
    parser.add_argument("--env", required=True)
    parser.add_argument("--adopt-demo-secret-version")
    args = parser.parse_args()
    try:
        deploy_outputs(args.config, args.env, sys.stdin, args.adopt_demo_secret_version)
    except (OpsError, ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Deployment failed: {error}\n")


if __name__ == "__main__":
    main()
