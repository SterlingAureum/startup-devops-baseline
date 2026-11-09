#!/usr/bin/env python3
"""Read-only recovery observation and offline Root deployment plan review. No execute phase."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "delivery/contracts/v0.11.9.3.6.7.5-aws-test-recovery-root-design.json"
CLUSTER = "startup-devops-baseline-test"
ALB = "aws-load-balancer-controller"
APP = "startup-devops-aws-test-root"
RELEASE = "demo-api-cf0a6bcbc466-cdffd3d71763"
REPO = "https://github.com/SterlingAureum/startup-devops-baseline.git"
STATE = "infra/terraform/aws/environments/test/terraform.tfstate"
COMPONENTS = {"eks", "ec2", "ebs", "nat_and_ipv4", "load_balancing",
              "storage_backups", "logs_metrics", "dns_and_other", "transfer"}
SCOPES = {"root_and_child_auto_sync", "compute_and_storage_controllers",
          "cnpg_backups_and_irsa", "eso_and_credential_transfer", "dns_reconciliation",
          "monitoring_reconciliation", "cleanup_and_failure_handling",
          "immutable_revision_strategy"}


def require(ok, label):
    if not ok:
        raise ValueError(label)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root, directory):
    rows = []
    for p in sorted((root / directory).rglob("*")):
        require(not p.is_symlink(), "source-symlink")
        if p.is_file():
            rows.append((str(p.relative_to(root)), digest(p)))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def load(path):
    def unique(pairs):
        data = {}
        for key, value in pairs:
            require(key not in data, "duplicate-json-key")
            data[key] = value
        return data
    return json.loads(path.read_text(), object_pairs_hook=unique)


def utc(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value), "utc-format")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def amount(value):
    require(isinstance(value, str), "money-must-be-decimal-string")
    result = Decimal(value)
    require(result.is_finite() and result >= 0, "invalid-money")
    return result


def private(path, mode=0o600):
    require(path.is_absolute(), "private-path-must-be-absolute")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "private-symlink")
    info = path.stat()
    require(info.st_uid == os.getuid(), "private-owner")
    require(stat.S_IMODE(info.st_mode) == mode, "private-mode")
    require(stat.S_ISDIR(info.st_mode) if mode == 0o700 else
            stat.S_ISREG(info.st_mode), "private-file-type")
    return path


def persistent(path, root=ROOT):
    resolved = path.resolve()
    require(not any(resolved.is_relative_to(p) for p in
                    (root.resolve(), Path("/tmp"), Path("/var/tmp"), Path("/run"))),
            "use-persistent-directory-outside-repository")


def write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def source_checks(root=ROOT):
    contract = load(root / CONTRACT)
    for item in contract["reviewedFiles"]:
        require(digest(root / item["path"]) == item["sha256"], "repository-file-drift")
    for p, expected in contract["reviewedTrees"].items():
        require(tree_digest(root, p) == expected, "repository-tree-drift")
    return contract


def git(args):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, timeout=60)
    require(r.returncode == 0, "git-check-failed")
    return r.stdout.decode().strip()


def exact_main(expected, baseline, runner=git):
    require(re.fullmatch(r"[0-9a-f]{40}", expected) is not None, "main-format")
    require(expected != baseline, "fresh-post-merge-main-required")
    require(runner(["branch", "--show-current"]) == "main", "main-branch-required")
    require(runner(["status", "--porcelain"]) == "", "clean-worktree-required")
    for ref in ("HEAD", "origin/main"):
        require(runner(["rev-parse", ref]) == expected, "main-drift")
    runner(["merge-base", "--is-ancestor", baseline, expected])
    require(runner(["ls-remote", "origin", "refs/heads/main"]) ==
            expected + "\trefs/heads/main", "remote-main-drift")


def local_inputs(path, expected_main):
    contract = source_checks()
    exact_main(expected_main, contract["implementationBaselineCommit"])
    data = load(private(path))
    require(set(data) == {"aws_account_id", "management_cidr", "kubeconfig_path",
                         "recovery_summary_path", "old_temporary_evidence_lost"}, "input-fields")
    require(data["old_temporary_evidence_lost"] is True, "lost-evidence-acknowledgment")
    require(isinstance(data["aws_account_id"], str) and
            re.fullmatch(r"[0-9]{12}", data["aws_account_id"]), "account-format")
    cidr = ipaddress.ip_network(data["management_cidr"], strict=True)
    require(cidr.version == 4 and cidr.prefixlen == 32 and cidr.network_address.is_global,
            "single-public-management-ip-required")
    for key, expected in (("kubeconfig_path", "kubeconfigSha256"),
                          ("recovery_summary_path", "observationSha256")):
        p = private(Path(data[key]))
        persistent(p)
        require(digest(p) == contract["recovery"][expected], "recovery-input-drift")
    state_path = private((ROOT / STATE).absolute())
    require(digest(state_path) == contract["recovery"]["stateSha256"], "state-drift")
    state = load(state_path)
    count = sum(len(r.get("instances", [])) for r in state["resources"])
    require(count == 103, "state-instance-count")
    return contract, data, state


def kube_auth(config, endpoint):
    require(len(config.get("clusters", [])) == 1, "kubeconfig-clusters")
    require(config["clusters"][0]["cluster"]["server"] == endpoint, "kubeconfig-endpoint")
    require(len(config.get("users", [])) == 1, "kubeconfig-users")
    user = config["users"][0]["user"]
    require(set(user) == {"exec"}, "unexpected-kubeconfig-auth")
    auth = user["exec"]
    require(auth.get("command") == "aws", "unexpected-exec-plugin")
    require(auth.get("args") == ["--region", "us-east-1", "eks", "get-token",
                                 "--cluster-name", CLUSTER, "--output", "json"],
            "unexpected-exec-arguments")
    for entry in auth.get("env") or []:
        require(entry.get("name") == "AWS_PROFILE" and entry.get("value") ==
                os.environ.get("AWS_PROFILE"), "unexpected-exec-environment")


def ready(obj):
    spec, status = obj.get("spec", {}), obj.get("status", {})
    replicas = spec.get("replicas", 1)
    require(type(replicas) is int and replicas > 0, "workload-replicas")
    require(status.get("readyReplicas", 0) == replicas, "workload-not-ready")
    require(status.get("observedGeneration") == obj["metadata"]["generation"],
            "workload-generation-not-observed")


def observe(args):
    stage = "local-inputs"
    output = args.output_directory
    private(output.parent, 0o700)
    persistent(output)
    require(not output.exists() and not output.is_symlink(), "output-must-be-new")
    output.mkdir(mode=0o700)
    try:
        contract, inputs, state = local_inputs(args.inputs, args.expected_main)
        environment = os.environ.copy()
        environment.update(AWS_PAGER="", AWS_MAX_ATTEMPTS="1", AWS_REGION="us-east-1",
                           AWS_DEFAULT_REGION="us-east-1")
        require(not any(k.startswith("AWS_ENDPOINT_URL") for k in environment),
                "custom-aws-endpoint-prohibited")

        def call(label, command, as_json=True):
            nonlocal stage
            stage = label
            with (output / (label + ".stdout")).open("xb") as stdout, \
                    (output / (label + ".stderr")).open("xb") as stderr:
                result = subprocess.run(command, stdout=stdout, stderr=stderr,
                                        timeout=120, env=environment, cwd=ROOT)
            require(result.returncode == 0, "read-command-failed")
            raw = (output / (label + ".stdout")).read_bytes()
            return json.loads(raw) if as_json else raw

        aws = ["aws", "--region", "us-east-1", "--output", "json"]
        identity = call("identity", aws + ["sts", "get-caller-identity"])
        require(identity.get("Account") == inputs["aws_account_id"], "account-mismatch")
        inventory = call("cluster-inventory", aws + ["eks", "list-clusters"])
        require(set(inventory["clusters"]) & {CLUSTER, "startup-devops-baseline-dev",
                "startup-devops-baseline-prod"} == {CLUSTER}, "rehearsal-inventory")
        cluster = call("cluster", aws + ["eks", "describe-cluster", "--name", CLUSTER])["cluster"]
        require(cluster.get("status") == "ACTIVE", "eks-not-active")
        network = cluster["resourcesVpcConfig"]
        require(network.get("endpointPublicAccess") is True and
                network.get("endpointPrivateAccess") is True and
                network.get("publicAccessCidrs") == [inputs["management_cidr"]], "api-boundary")
        outputs = {k: v["value"] for k, v in state["outputs"].items()}
        require(network["vpcId"] == outputs["vpc_id"], "vpc-state-mismatch")
        metadata = call("metadata-observation", aws + ["secretsmanager", "describe-secret",
                        "--secret-id", outputs["external_secrets_secret_arn"]])
        require(metadata.get("ARN") == outputs["external_secrets_secret_arn"] and
                not metadata.get("DeletedDate"), "metadata-container-mismatch")
        kube = ["kubectl", "--kubeconfig", inputs["kubeconfig_path"],
                "--context=aws-test", "--request-timeout=30s"]
        kube_auth(call("kubeconfig", kube + ["config", "view", "--minify", "-o", "json"]),
                  cluster["endpoint"])
        require(call("readyz", kube + ["get", "--raw=/readyz"], False).strip() == b"ok", "api-not-ready")
        for kind, name, namespace in (("deployment", "argocd-server", "argocd"),
                ("deployment", "argocd-repo-server", "argocd"),
                ("statefulset", "argocd-application-controller", "argocd"),
                ("deployment", ALB, "kube-system")):
            obj = call(name, kube + ["get", kind, name, "-n", namespace, "-o", "json"])
            ready(obj)
            if namespace == "argocd":
                images = [c.get("image") for c in obj["spec"]["template"]["spec"]["containers"]]
                require("quay.io/argoproj/argocd:v3.5.2" in images, "argocd-version")
        for name, key in ((ALB, "aws_load_balancer_controller_role_arn"),
                          ("karpenter", "karpenter_controller_role_arn")):
            sa = call(name + "-irsa", kube + ["get", "serviceaccount", name,
                                             "-n", "kube-system", "-o", "json"])
            require(sa["metadata"].get("annotations", {}).get("eks.amazonaws.com/role-arn")
                    == outputs[key], "irsa-mismatch")
        apps = call("applications", kube + ["get", "applications.argoproj.io",
                                            "-n", "argocd", "-o", "json"])["items"]
        require(len(apps) == 1 and apps[0]["metadata"]["name"] == ALB, "application-inventory")
        alb = apps[0]
        require(alb.get("status", {}).get("sync", {}).get("status") == "Synced" and
                alb.get("status", {}).get("health", {}).get("status") == "Healthy", "alb-health")
        source = alb["spec"]["source"]
        require(source.get("chart") == ALB and source.get("targetRevision") == "1.14.0",
                "alb-chart-identity")
        values = source["helm"]["valuesObject"]
        require(values.get("vpcId") == outputs["vpc_id"] and
                values.get("clusterName") == CLUSTER and values.get("region") == "us-east-1",
                "alb-target-identity")
        # Cost observations are inventories, never a billed-spend claim.
        instances = call("compute-inventory", aws + ["ec2", "describe-instances", "--filters",
            "Name=vpc-id,Values=" + outputs["vpc_id"]])
        by_type = {}
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] not in ("terminated", "shutting-down"):
                    t = instance["InstanceType"]
                    by_type[t] = by_type.get(t, 0) + 1
        volumes = call("volume-inventory", aws + ["ec2", "describe-volumes", "--filters",
            "Name=tag:kubernetes.io/cluster/" + CLUSTER + ",Values=owned,shared"])
        stage = "final-local-recheck"
        local_inputs(args.inputs, args.expected_main)
        summary = {"status": "aws-test-recovery-root-preflight-complete",
                   "observed_at_utc": timestamp(), "control_plane_commit": args.expected_main,
                   "candidate_release_id": RELEASE, "recovery_summary_sha256":
                   contract["recovery"]["observationSha256"],
                   "kubeconfig_sha256": contract["recovery"]["kubeconfigSha256"],
                   "terraform_state_sha256": contract["recovery"]["stateSha256"],
                   "private_inputs_sha256": digest(args.inputs),
                   "account_verified": True, "eks_active": True,
                   "argocd_ready": True, "alb_synced_healthy": True,
                   "root_application_absent": True, "state_address_count": 103,
                   "compute_counts_by_type": by_type,
                   "tag_matched_volume_count": len(volumes["Volumes"]),
                   "volume_inventory_exhaustive": False,
                   "historical_spend_usd": None, "additional_budget_limit_usd": "8.00",
                   "root_deployment_authorized": False, "mutation_executed": False}
        write(output / "summary.json", summary)
        return summary
    except Exception:
        write(output / "failure.json", {"status": "stopped", "stage": stage,
                                       "mutation_executed": False, "automatic_retry": False})
        raise ValueError("observation-stopped-preserve-private-output") from None


def check_plan(plan, observation, contract, now):
    cost = contract["cost"]
    require(observation["status"] == "aws-test-recovery-root-preflight-complete", "observation-status")
    age = (now - utc(observation["observed_at_utc"])).total_seconds()
    require(0 <= age <= cost["observationTtlSeconds"], "observation-expired-or-future")
    require(plan["target_environment"] == "aws-test", "plan-target")
    require(plan["control_plane_commit"] == observation["control_plane_commit"], "plan-main")
    require(plan["candidate_release_id"] == RELEASE, "plan-release")
    require(plan["historical_spend_usd"] is None and
            plan["historical_spend_unattributed"] is True, "unknown-history-must-be-preserved")
    require(amount(plan["additional_budget_limit_usd"]) == Decimal("8"), "budget-limit")
    start, end = utc(plan["start_utc"]), utc(plan["cleanup_complete_by_utc"])
    anchor = utc(cost["conservativeAccountingStartUtc"])
    require(anchor <= now <= start < end <= utc(cost["operatorAvailableUntilUtc"]), "window-boundary")
    seconds = (end - start).total_seconds()
    require(seconds <= cost["maximumNewWindowSeconds"], "eight-hour-limit")
    reserve = plan["cleanup_reserve_seconds"]
    require(type(reserve) is int and cost["minimumCleanupReserveSeconds"] <= reserve < seconds,
            "cleanup-reserve")
    require(set(plan["hourly_upper_bound_usd"]) == COMPONENTS, "cost-components")
    hourly = sum((amount(v) for v in plan["hourly_upper_bound_usd"].values()), Decimal(0))
    require(hourly > 0, "hourly-estimate-required")
    require(plan["estimate_covers_idle_and_post_root_peak"] is True and
            plan["estimate_covers_all_resources_not_only_tag_matches"] is True, "estimate-scope")
    require(isinstance(plan["pricing_reference"], str) and
            len(plan["pricing_reference"].strip()) >= 16 and
            "__" not in plan["pricing_reference"], "pricing-reference-required")
    estimate = hourly * Decimal(str((end - anchor).total_seconds())) / Decimal(3600)
    estimate += amount(plan["fixed_and_uncertainty_reserve_usd"])
    require(estimate <= Decimal("8"), "additional-budget-exceeded-including-elapsed-time")
    require(set(plan["reviewed_scope"]) == SCOPES and
            all(v is True for v in plan["reviewed_scope"].values()), "root-cascade-review-required")
    for key in ("root_deployment_authorized", "credential_transfer_authorized",
                "dns_write_authorized", "teardown_authorized", "automatic_budget_enforcement"):
        require(plan[key] is False, "design-is-not-execution-approval")
    return {"status": "aws-test-private-root-plan-reviewed-offline",
            "estimated_additional_cost_usd": str(estimate),
            "historical_spend_usd": None, "additional_budget_limit_usd": "8.00",
            "root_deployment_authorized": False, "mutation_executed": False,
            "next_action": contract["nextCheckpoint"]}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    obs = sub.add_parser("observe")
    obs.add_argument("--inputs", type=Path, required=True)
    obs.add_argument("--expected-main", required=True)
    obs.add_argument("--output-directory", type=Path, required=True)
    plan = sub.add_parser("check-plan")
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--observation", type=Path, required=True)
    plan.add_argument("--expected-observation-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.phase == "observe":
            result = observe(args)
        else:
            contract = source_checks()
            private(args.plan)
            private(args.observation)
            persistent(args.plan)
            persistent(args.observation)
            require(digest(args.observation) == args.expected_observation_sha256, "observation-hash")
            data = load(args.plan)
            require(data["observation_sha256"] == args.expected_observation_sha256, "plan-observation")
            result = check_plan(data, load(args.observation), contract, datetime.now(timezone.utc))
        print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, InvalidOperation, KeyError, TypeError, OSError, subprocess.SubprocessError):
        parser.exit(1, "Stopped: inputs or observation failed; preserve private evidence. No mutation or retry.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
