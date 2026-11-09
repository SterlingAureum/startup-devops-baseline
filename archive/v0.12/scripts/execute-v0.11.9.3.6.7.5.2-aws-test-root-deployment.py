#!/usr/bin/env python3
"""Prepare, verify or separately execute one pinned aws-test Root deployment."""
import argparse
import base64
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid

import aws_test_immutable_root as h

p = h.p
AWS = ["aws", "--region", "us-east-1", "--output", "json"]


class Runner:
    def __init__(self, output, inputs, stop, state_hash):
        self.output, self.stop, self.state_hash = output, stop, state_hash
        self.inputs = inputs
        self.sequence = 0
        self.stage = "local-inputs"
        self.mutation_attempted = False
        self.environment = os.environ.copy()
        self.environment.update(AWS_MAX_ATTEMPTS="1", AWS_PAGER="", AWS_REGION="us-east-1", AWS_DEFAULT_REGION="us-east-1")
        self.kube = ["kubectl", "--kubeconfig", inputs["kubeconfig_path"], "--context=aws-test", "--request-timeout=30s"]

    def check_time_and_state(self):
        remaining = (self.stop - h.now()).total_seconds()
        p.require(remaining > 1, "operation-deadline-reached")
        p.require(p.digest(h.ROOT / p.STATE) == self.state_hash, "terraform-state-changed")
        return remaining

    def call(self, label, command, payload=None, mutation=False, optional=False):
        remaining = self.check_time_and_state()
        self.stage = label
        self.sequence += 1
        prefix = f"{self.sequence:04d}-{label}"
        if mutation:
            self.mutation_attempted = True
            fd = os.open(self.output / "mutation-attempts.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as journal:
                journal.write(json.dumps({"sequence": self.sequence, "stage": label, "at_utc": p.timestamp(),
                                          "command_attempted": True, "success_not_yet_known": True}) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
        with (self.output / (prefix + ".stdout")).open("xb") as stdout, \
                (self.output / (prefix + ".stderr")).open("xb") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, env=self.environment, cwd=h.ROOT, start_new_session=True)
            try:
                process.communicate(input=payload, timeout=min(remaining, 120))
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait()
                raise
        p.require(process.returncode == 0, "command-failed-preserve-evidence")
        raw = (self.output / (prefix + ".stdout")).read_bytes()
        if optional and not raw.strip():
            return {}
        return json.loads(raw) if raw.strip() else {}

    def get(self, label, kind, name, namespace=None, optional=False):
        command = self.kube + ["get", kind]
        if name:
            command.append(name)
        if namespace:
            command += ["-n", namespace]
        if optional:
            command += ["--ignore-not-found=true"]
        return self.call(label, command + ["-o", "json"], optional=optional)

    def apply(self, label, objects):
        # kubectl may print multiple JSON documents for a List; apply one object
        # per call so response parsing cannot fail after a successful multi-apply.
        result = []
        for index, obj in enumerate(objects):
            result.append(self.call(label + "-" + str(index), self.kube + ["apply", "-f", "-", "-o", "json"],
                                    json.dumps(obj).encode(), mutation=True))
        return result

    def wait(self, label, read, condition):
        while True:
            value = read()
            if condition(value):
                return value
            self.stage = label
            remaining = self.check_time_and_state()
            time.sleep(min(10, max(0, remaining - 1)))


def source_recheck(bundle, main, outputs, c, output, runner):
    work = output / "render-recheck"
    work.mkdir(mode=0o700)
    def builder(directory):
        value = runner.call("render-check", [sys.executable, "-c",
            "import subprocess,json,yaml,sys; r=subprocess.run(['kubectl','kustomize',sys.argv[1]],capture_output=True); "
            "sys.exit(r.returncode) if r.returncode else print(json.dumps(list(yaml.safe_load_all(r.stdout))))", str(directory)])
        return value
    h.render_bundle(c, main, outputs, work, builder=builder)
    for name in ("root-application.json", "rendered-root-resources.json", "application-source-map.json", "rendered-postgresql-resources.json"):
        p.require(p.digest(work / name) == p.digest(bundle / name), "re-render-byte-mismatch")


def metadata(runner, outputs, label):
    value = runner.call(label, AWS + ["secretsmanager", "describe-secret", "--secret-id", outputs["external_secrets_secret_arn"]])
    p.require(value.get("ARN") == outputs["external_secrets_secret_arn"] and
              value.get("Name") == outputs["external_secrets_secret_name"] and not value.get("DeletedDate"), "metadata-target")
    return value


def record_absent(runner, zone):
    value = runner.call("dns-record-inventory", AWS + ["route53", "list-resource-record-sets", "--hosted-zone-id", zone])
    p.require(not any(x["Name"] == "demo.test.aureumstack.com." and x["Type"] in ("A", "AAAA", "CNAME")
                      for x in value["ResourceRecordSets"]), "test-dns-record-already-exists")


def extra_preflight(runner, outputs):
    p.require(not metadata(runner, outputs, "metadata-empty").get("VersionIdsToStages"), "initial-container-must-have-no-versions")
    clusters = runner.call("compute-targets", AWS + ["ec2", "describe-instances", "--filters",
                           "Name=vpc-id,Values=" + outputs["vpc_id"]])
    instances = [i for r in clusters["Reservations"] for i in r["Instances"]
                 if i["State"]["Name"] not in ("terminated", "shutting-down")]
    p.require(len(instances) == 4 and all(i["InstanceType"] == "t3.medium" and
              i["State"]["Name"] == "running" and not i.get("InstanceLifecycle") and not i.get("PublicIpAddress")
              for i in instances), "unexpected-live-compute")
    state = p.load(h.ROOT / p.STATE)
    groups = {g["name"] for resource in state["resources"] if resource.get("type") == "aws_eks_node_group"
              for instance in resource["instances"] for res in instance["attributes"]["resources"]
              for g in res["autoscaling_groups"]}
    p.require(len(groups) == 1 and all(any(t["Key"] == "aws:autoscaling:groupName" and t["Value"] in groups
              for t in i.get("Tags", [])) for i in instances), "system-nodegroup-association")
    volumes = runner.call("attached-volumes", AWS + ["ec2", "describe-volumes", "--filters",
        "Name=attachment.instance-id,Values=" + ",".join(i["InstanceId"] for i in instances)])["Volumes"]
    p.require(len(volumes) == 4 and all(v["VolumeType"] == "gp3" and v["Size"] == 30 and
              v["Iops"] == 3000 and v["Throughput"] == 125 for v in volumes), "baseline-disk-inventory")
    lbs = runner.call("load-balancers-before-root", AWS + ["elbv2", "describe-load-balancers"])["LoadBalancers"]
    p.require(not any(x["VpcId"] == outputs["vpc_id"] for x in lbs), "existing-vpc-load-balancer")
    nats = runner.call("nat-inventory", AWS + ["ec2", "describe-nat-gateways", "--filter",
                       "Name=vpc-id,Values=" + outputs["vpc_id"]])["NatGateways"]
    nats = [n for n in nats if n["State"] not in ("deleted", "failed")]
    p.require(len(nats) == 1 and nats[0]["State"] == "available" and
              len(nats[0]["NatGatewayAddresses"]) == 1, "nat-inventory")
    config = runner.get("argocd-config", "configmap", "argocd-cm", "argocd")
    p.require(not any(k.startswith("kustomize.") and v for k, v in config.get("data", {}).items()),
              "custom-argocd-kustomize-configuration")
    zones = runner.call("hosted-zone", AWS + ["route53", "list-hosted-zones-by-name", "--dns-name", "aureumstack.com"])
    selected = [z for z in zones["HostedZones"] if z["Name"] == "aureumstack.com." and not z["Config"]["PrivateZone"]]
    p.require(len(selected) == 1, "single-public-zone-required")
    zone = selected[0]["Id"].removeprefix("/hostedzone/")
    record_absent(runner, zone)
    return zone


def preflight(args, c, output, runner):
    observation = runner.call("recovery-preflight", [sys.executable,
        str(h.ROOT / "scripts/check-v0.11.9.3.6.7.5-aws-test-recovery-root-plan.py"), "observe",
        "--inputs", str(args.inputs), "--expected-main", args.expected_main,
        "--output-directory", str(output / "recovery-preflight")])
    p.require(observation["compute_counts_by_type"] == {"t3.medium": 4}, "baseline-compute-count")
    live_cluster = p.load(output / "recovery-preflight/cluster.stdout")["cluster"]
    p.require(live_cluster["version"] == "1.36" and not live_cluster.get("computeConfig", {}).get("enabled"),
              "eks-cost-support-tier")
    _, inputs, state = p.local_inputs(args.inputs, args.expected_main)
    outputs = {key: item["value"] for key, item in state["outputs"].items()}
    h.validate_outputs(outputs, inputs["aws_account_id"])
    zone = extra_preflight(runner, outputs)
    stable = dict(observation)
    stable.pop("observed_at_utc")
    source_recheck(args.bundle, args.expected_main, outputs, c, output, runner)
    return outputs, zone, h.hash_value(stable)


def wait_app(runner, name, commit, healthy=True):
    def ready(app):
        if not app:
            return False
        source = app["spec"]["source"]
        if source["repoURL"] == p.REPO:
            p.require(source["targetRevision"] == commit, "live-child-revision-drift")
        status = app.get("status", {})
        return status.get("sync", {}).get("status") == "Synced" and (
            not healthy or status.get("health", {}).get("status") == "Healthy")
    return runner.wait("wait-" + name, lambda: runner.get("application-" + name, "application", name, "argocd", True), ready)


def secret_uri(obj, key):
    value = base64.b64decode(obj["data"][key], validate=True).decode()
    parsed = urlparse(value)
    p.require(parsed.scheme == "postgresql" and parsed.username == "app" and parsed.password and
              parsed.path == "/app" and parsed.hostname in {"postgresql-baseline-rw.data-platform.svc.cluster.local",
                  "postgresql-baseline-rw.data-platform.svc", "postgresql-baseline-rw.data-platform"},
              "cnpg-credential-identity")
    return value


def deploy(runner, bundle, c, main, outputs, zone, token):
    annotations = lambda arn: {"eks.amazonaws.com/role-arn": arn}
    namespaces = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "external-secrets",
        "labels": {"pod-security.kubernetes.io/enforce": "restricted", "pod-security.kubernetes.io/enforce-version": "v1.30",
                   "pod-security.kubernetes.io/warn": "restricted", "pod-security.kubernetes.io/audit": "restricted"}}},
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "data-platform"}}]
    accounts = [{"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": name, "namespace": ns,
                  "annotations": annotations(outputs[key])}} for name, ns, key in (
                  ("external-secrets", "external-secrets", "external_secrets_role_arn"),
                  ("postgresql-baseline", "data-platform", "cnpg_backup_role_arn"))]
    runner.apply("prepare-namespaces", namespaces)
    runner.apply("prepare-irsa-accounts", accounts)
    runner.apply("deploy-pinned-root", [p.load(bundle / "root-application.json")])
    for name in ("cert-manager", "cloudnative-pg", "barman-cloud-plugin", "external-secrets", "karpenter"):
        wait_app(runner, name, main)
    wait_app(runner, "postgresql-baseline", main)
    runner.wait("wait-database-ready", lambda: runner.get("database-ready", "clusters.postgresql.cnpg.io",
                "postgresql-baseline", "data-platform"), lambda o: o.get("status", {}).get("readyInstances") == 3 and
                any(x.get("type") == "Ready" and x.get("status") == "True" for x in o.get("status", {}).get("conditions", [])))
    uri = secret_uri(runner.get("cnpg-app-credential", "secret", "postgresql-baseline-app", "data-platform"), "fqdn-uri")
    p.require(not metadata(runner, outputs, "metadata-before-seed").get("VersionIdsToStages"), "refuse-existing-version-overwrite")
    payload = json.dumps({"DATABASE_URL": uri})
    runner.call("initial-credential-version", AWS + ["secretsmanager", "put-secret-value", "--secret-id",
        outputs["external_secrets_secret_arn"], "--client-request-token", token,
        "--secret-string", "file:///dev/stdin"], payload.encode(), mutation=True)
    returned = runner.call("credential-readback", AWS + ["secretsmanager", "get-secret-value", "--secret-id",
                           outputs["external_secrets_secret_arn"], "--version-id", token])
    p.require(json.loads(returned["SecretString"]) == {"DATABASE_URL": uri}, "credential-readback-mismatch")
    wait_app(runner, "external-secrets-startup-apps", main, healthy=False)
    runner.call("external-secret-refresh", runner.kube + ["annotate", "externalsecret", "demo-api-postgresql", "-n",
                "startup-apps", "force-sync=" + token, "--overwrite", "-o", "json"], mutation=True)
    runner.wait("wait-external-secret", lambda: runner.get("external-secret-ready", "externalsecret",
                "demo-api-postgresql", "startup-apps"), lambda o: any(x.get("type") == "Ready" and x.get("status") == "True"
                for x in o.get("status", {}).get("conditions", [])))
    target = runner.get("eso-target-credential", "secret", "demo-api-postgresql", "startup-apps")
    p.require(base64.b64decode(target["data"]["DATABASE_URL"], validate=True).decode() == uri, "eso-credential-mismatch")
    del uri, payload, returned, target
    wait_app(runner, "external-secrets-startup-apps", main)
    wait_app(runner, "monitoring-aws-test", main)
    wait_app(runner, "observability-views-aws-test", main)
    wait_app(runner, "demo-api-aws-test", main, healthy=False)
    ingress = runner.wait("wait-ingress-alb", lambda: runner.get("application-ingress", "ingress", "demo-api",
        "startup-apps", True), lambda o: bool(o.get("status", {}).get("loadBalancer", {}).get("ingress")))
    hostname = ingress["status"]["loadBalancer"]["ingress"][0]["hostname"]
    p.require(hostname.endswith(".elb.amazonaws.com"), "ingress-dns-suffix")
    def matching_lb(inventory):
        matches = [x for x in inventory["LoadBalancers"] if x["DNSName"] == hostname]
        if not matches:
            return False
        p.require(len(matches) == 1 and matches[0]["VpcId"] == outputs["vpc_id"] and
                  matches[0]["Type"] == "application" and matches[0]["Scheme"] == "internet-facing", "alb-ownership")
        return matches[0]["State"]["Code"] == "active"
    lbs = runner.wait("wait-alb-active", lambda: runner.call("application-alb", AWS + ["elbv2", "describe-load-balancers"]), matching_lb)
    lb = next(x for x in lbs["LoadBalancers"] if x["DNSName"] == hostname)
    tags = runner.call("alb-owner-tags", AWS + ["elbv2", "describe-tags", "--resource-arns", lb["LoadBalancerArn"]])
    tagmap = {t["Key"]: t["Value"] for t in tags["TagDescriptions"][0]["Tags"]}
    p.require(tagmap.get("elbv2.k8s.aws/cluster") == p.CLUSTER and
              tagmap.get("ingress.k8s.aws/stack") == "startup-apps/demo-api", "alb-controller-tags")
    record_absent(runner, zone)
    record = {"Name": "demo.test.aureumstack.com.", "Type": "A", "AliasTarget": {
        "HostedZoneId": lb["CanonicalHostedZoneId"], "DNSName": "dualstack." + hostname.rstrip(".") + ".",
        "EvaluateTargetHealth": True}}
    change = runner.call("test-alias-upsert", AWS + ["route53", "change-resource-record-sets", "--hosted-zone-id", zone,
                         "--change-batch", "file:///dev/stdin"],
                         json.dumps({"Changes": [{"Action": "UPSERT", "ResourceRecordSet": record}]}).encode(), mutation=True)
    runner.wait("wait-dns-insync", lambda: runner.call("dns-change-status", AWS + ["route53", "get-change", "--id",
                change["ChangeInfo"]["Id"]]), lambda o: o["ChangeInfo"]["Status"] == "INSYNC")
    for item in c["applications"]:
        wait_app(runner, item["name"], main, healthy=item["name"] != "demo-api-aws-test")
    wait_app(runner, p.APP, main, healthy=False)
    return postchecks(runner, bundle, c, main, outputs, zone, record)


def postchecks(runner, bundle, c, main, outputs, zone, record):
    root = runner.get("root-final", "application", p.APP, "argocd")
    p.require(root["spec"] == p.load(bundle / "root-application.json")["spec"] and
              root.get("status", {}).get("sync", {}).get("status") == "Synced" and
              root.get("status", {}).get("sync", {}).get("revision") == main, "root-postcheck")
    allowed_health = {"Healthy", "Progressing", "Suspended"}
    p.require(root.get("status", {}).get("health", {}).get("status") in allowed_health, "root-health-postcheck")
    inventory = runner.get("children-final", "applications.argoproj.io", "", "argocd")
    expected = {o["name"]: o for o in p.load(bundle / "application-source-map.json")}
    children = [o for o in inventory["items"] if o["metadata"]["name"] != p.APP]
    p.require({o["metadata"]["name"] for o in children} == set(expected), "child-post-inventory")
    for app in children:
        name = app["metadata"]["name"]
        p.require(app["spec"]["source"] == expected[name]["source"] and
                  app["spec"]["destination"] == expected[name]["destination"] and
                  app.get("status", {}).get("sync", {}).get("status") == "Synced", "child-post-source-sync")
        if app["spec"]["source"]["repoURL"] == p.REPO:
            p.require(app["status"]["sync"].get("revision") == main, "child-post-revision")
        health = app.get("status", {}).get("health", {}).get("status")
        p.require(health in allowed_health if name == "demo-api-aws-test" else health == "Healthy", "child-post-health")
    cluster = runner.get("database-final", "clusters.postgresql.cnpg.io", "postgresql-baseline", "data-platform")
    p.require(cluster.get("status", {}).get("readyInstances") == 3 and
              any(x.get("type") == "Ready" and x.get("status") == "True" for x in cluster.get("status", {}).get("conditions", [])),
              "database-final-readiness")
    external = runner.get("external-secret-final", "externalsecret", "demo-api-postgresql", "startup-apps")
    p.require(any(x.get("type") == "Ready" and x.get("status") == "True" for x in external.get("status", {}).get("conditions", [])),
              "external-secret-final-readiness")
    nodepools = runner.get("nodepools-final", "nodepools", "")
    p.require({o["metadata"]["name"] for o in nodepools["items"]} == {"database-ondemand", "application-ondemand"}, "nodepool-postscope")
    for pool in nodepools["items"]:
        requirements = {r["key"]: r for r in pool["spec"]["template"]["spec"]["requirements"]}
        p.require(requirements["node.kubernetes.io/instance-type"]["values"] == ["c6i.large"], "post-pool-machine")
    nodes = runner.get("nodes-final", "nodes", "")
    new_nodes = [o for o in nodes["items"] if o["metadata"].get("labels", {}).get("karpenter.sh/nodepool")]
    p.require(len(new_nodes) <= 7 and all(o["metadata"]["labels"].get("node.kubernetes.io/instance-type") == "c6i.large" and
              o["metadata"]["labels"].get("karpenter.sh/capacity-type") == "on-demand" for o in new_nodes), "post-node-cost-envelope")
    for name, namespace, key in (("external-secrets", "external-secrets", "external_secrets_role_arn"),
                                 ("postgresql-baseline", "data-platform", "cnpg_backup_role_arn")):
        sa = runner.get("final-sa-" + name, "serviceaccount", name, namespace)
        p.require(sa["metadata"].get("annotations", {}).get("eks.amazonaws.com/role-arn") == outputs[key], "post-irsa")
    store = runner.get("objectstore-final", "objectstores.barmancloud.cnpg.io", "postgresql-baseline-backup", "data-platform")
    p.require(store["spec"]["configuration"]["destinationPath"] == "s3://" + outputs["cnpg_backup_bucket_name"] + "/postgresql-baseline", "backup-post-target")
    dns = runner.call("alias-final", AWS + ["route53", "list-resource-record-sets", "--hosted-zone-id", zone])
    p.require(record in dns["ResourceRecordSets"], "alias-postcheck")
    p.exact_main(main, c["implementationBaselineCommit"])
    runner.check_time_and_state()
    return {"status": "aws-test-immutable-root-deployment-complete", "root_deployed": True,
            "database_ready": True, "credential_seeded_and_eso_verified": True, "dns_alias_insync": True,
            "same_repository_revisions_pinned": True, "terraform_state_unchanged": True,
            "root_health": root["status"]["health"]["status"],
            "demo_application_health": next(o["status"]["health"]["status"] for o in children if o["metadata"]["name"] == "demo-api-aws-test"),
            "qualification_executed": False, "traffic_generated": False, "automatic_retry_performed": False,
            "automatic_teardown_executed": False, "next_action": "review-runtime-health-and-independent-cleanup-before-deadline"}


def validate_verify(args, c):
    verify = h.read_private(args.verify_result)
    p.require(p.digest(args.verify_result) == args.expected_verify_sha256, "verify-hash")
    p.require(verify["status"] == "aws-test-immutable-root-deployment-inputs-verified" and
              verify["control_plane_commit"] == args.expected_main and
              all(verify[key] is False for key in ("root_deployment_authorized", "credential_transfer_authorized",
                                                   "dns_write_authorized", "mutation_executed")), "verify-target-status")
    p.require(verify["private_plan_sha256"] == p.digest(args.bundle / "private-root-plan.json"), "verify-plan-bytes")
    age = (h.now() - p.utc(verify["verified_at_utc"])).total_seconds()
    p.require(0 <= age <= c["budget"]["verifyTtlSeconds"], "verify-expired")
    p.require(str(uuid.UUID(verify["attempt_token"])) == verify["attempt_token"] and
              uuid.UUID(verify["attempt_token"]).version == 4, "attempt-token-format")
    return verify


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    for phase in ("prepare", "verify", "execute"):
        command = sub.add_parser(phase)
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--expected-main", required=True)
        command.add_argument("--bundle", type=Path, required=True)
        if phase != "prepare":
            command.add_argument("--output-directory", type=Path, required=True)
        if phase == "execute":
            command.add_argument("--verify-result", type=Path, required=True)
            command.add_argument("--expected-verify-sha256", required=True)
    args = parser.parse_args()
    runner = None
    try:
        c = h.source_checks()
        h.assert_confirmations(os.environ, args.phase == "execute")
        p.exact_main(args.expected_main, c["implementationBaselineCommit"])
        _, inputs, state = p.local_inputs(args.inputs, args.expected_main)
        h.read_private(args.inputs)
        outputs = {key: item["value"] for key, item in state["outputs"].items()}
        h.validate_outputs(outputs, inputs["aws_account_id"])
        estimate = h.budget(c, h.now())
        if args.phase == "prepare":
            h.new_directory(args.bundle)
            h.render_bundle(c, args.expected_main, outputs, args.bundle)
            plan = {"expected_main": args.expected_main, "inputs_sha256": p.digest(args.inputs),
                    "root_manifest_sha256": p.digest(args.bundle / "root-application.json"),
                    "render_sha256": p.digest(args.bundle / "rendered-root-resources.json"),
                    "postgresql_render_sha256": p.digest(args.bundle / "rendered-postgresql-resources.json"),
                    "source_map_sha256": p.digest(args.bundle / "application-source-map.json"),
                    "contract_sha256": p.digest(h.ROOT / h.CONTRACT), "created_at_utc": p.timestamp(),
                    "cleanup_complete_by_utc": c["budget"]["cleanupCompleteByUtc"], "total_budget_limit_usd": "36.00",
                    "cost_model": estimate, "human_manifest_reviewed": False, "human_cost_scope_reviewed": False}
            p.write(args.bundle / "private-root-plan.json", plan)
            print(json.dumps({"status": "aws-test-private-immutable-root-plan-prepared", **estimate,
                              "root_manifest_sha256": plan["root_manifest_sha256"], "root_deployment_authorized": False}, indent=2))
            return 0
        plan = h.validate_bundle(args.bundle, args.inputs, args.expected_main, c)
        h.new_directory(args.output_directory)
        stop = min(p.utc(estimate["mutation_stop_utc"]), h.now() + timedelta(seconds=c["budget"]["maximumDeploymentSeconds"]))
        runner = Runner(args.output_directory, inputs, stop, p.digest(h.ROOT / p.STATE))
        if args.phase == "execute":
            verify = validate_verify(args, c)
            p.write(args.bundle / "one-time-execution-attempt.json", {"at_utc": p.timestamp(), "verify_sha256": args.expected_verify_sha256,
                    "outcome_not_yet_known": True, "automatic_retry_allowed": False})
        outputs, zone, stable = preflight(args, c, args.output_directory, runner)
        p.exact_main(args.expected_main, c["implementationBaselineCommit"])
        h.validate_bundle(args.bundle, args.inputs, args.expected_main, c)
        if args.phase == "verify":
            result = {"status": "aws-test-immutable-root-deployment-inputs-verified", "verified_at_utc": p.timestamp(),
                      "control_plane_commit": args.expected_main, "private_plan_sha256": p.digest(args.bundle / "private-root-plan.json"),
                      "root_manifest_sha256": plan["root_manifest_sha256"], "stable_preflight_sha256": stable,
                      "attempt_token": str(uuid.uuid4()), **h.budget(c, h.now()),
                      "root_deployment_authorized": False, "credential_transfer_authorized": False, "dns_write_authorized": False,
                      "mutation_executed": False, "next_action": "obtain-separate-root-credential-dns-execution-approval"}
        else:
            p.require(stable == verify["stable_preflight_sha256"], "immediate-preflight-drift")
            h.budget(c, h.now())
            result = deploy(runner, args.bundle, c, args.expected_main, outputs, zone, verify["attempt_token"])
            result.update(control_plane_commit=args.expected_main, reviewed_verify_sha256=args.expected_verify_sha256,
                          root_manifest_sha256=plan["root_manifest_sha256"])
        p.write(args.output_directory / "result.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        if runner:
            failure = {"status": "aws-test-root-deployment-stopped", "stage": runner.stage,
                       "mutation_attempted": runner.mutation_attempted, "outcome_requires_read_only_review": True,
                       "automatic_retry_performed": False, "automatic_repair_performed": False,
                       "controllers_may_continue_reconciling": runner.mutation_attempted}
            try:
                p.write(args.output_directory / "failure.json", failure)
            except OSError:
                pass
            print(json.dumps(failure, indent=2, sort_keys=True))
        parser.exit(1, "Stopped: preserve state, kubeconfig and all private evidence. No automatic retry, repair or teardown.\n")


if __name__ == "__main__":
    sys.exit(main())
