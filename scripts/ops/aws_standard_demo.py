"""Standard demo integration for the personal AWS GitOps stack."""
import base64
import json
import shlex
import time
import uuid

from aws_eso_bootstrap import EXTERNAL, wait_for_consumer
from configuration import OpsError, require


BOOTSTRAP = "BASELINE_BOOTSTRAP"
REBUILD = "BASELINE_CLI_DEMO_DB_REBUILD_V1"
MARKER = "platform.startup.dev/demo-db-version"


def database_version(g, arn, name, uri, adopt):
    metadata = json.loads(g.aws("secretsmanager", "describe-secret", "--secret-id", arn))
    require(metadata["ARN"] == arn and metadata["Name"] == name and not metadata.get("DeletedDate"),
            "Demo ExternalSecret and Terraform secret differ")
    stages = metadata.get("VersionIdsToStages", {})
    current = next((v for v in stages if "AWSCURRENT" in stages[v]), None)
    require(not adopt or current == adopt,
            "AWSCURRENT changed since the requested demo credential adoption")
    payload = {}
    if current:
        raw = json.loads(g.aws("secretsmanager", "get-secret-value", "--secret-id", arn, "--version-id", current,
                               "--version-stage", "AWSCURRENT", private=True))
        require(isinstance(raw.get("SecretString"), str), "Demo credential requires a JSON SecretString")
        payload = json.loads(raw["SecretString"])
        require(isinstance(payload, dict) and isinstance(payload.get("DATABASE_URL"), str),
                "Expected a DATABASE_URL string in the standard demo secret")
        managed = bool(set(stages[current]) & {BOOTSTRAP, REBUILD})
        if payload["DATABASE_URL"] == uri and (adopt != current or managed):
            return current
        require(managed or adopt == current, "CNPG and operator-managed AWSCURRENT differ. "
                "To transfer this standard demo version to the CLI, deploy with --adopt-demo-secret-version " + current)
    require(not metadata.get("RotationEnabled") and not any("AWSPENDING" in labels for labels in stages.values()),
            "Demo secret has active rotation; reconcile with its owner")
    require(current or all(set(labels) <= {BOOTSTRAP, REBUILD} for labels in stages.values()),
            "Demo secret contains unrecognized pending versions")
    # Alternate labels so a failed promotion leaves the old AWSCURRENT ownership intact.
    label = REBUILD if BOOTSTRAP in stages.get(current, []) else BOOTSTRAP
    token = str(uuid.uuid4())
    payload["DATABASE_URL"] = uri
    written = json.loads(g.aws(
        "secretsmanager", "put-secret-value", "--secret-id", arn, "--client-request-token", token,
        "--version-stages", label, "--secret-string", "file:///dev/stdin", data=json.dumps(payload), private=True))
    if not current and "AWSCURRENT" in written.get("VersionStages", []):
        return token
    args = ["--remove-from-version-id", current] if current else []
    g.aws("secretsmanager", "update-secret-version-stage", "--secret-id", arn, "--version-stage", "AWSCURRENT",
          "--move-to-version-id", token, *args)
    return token


def refresh_consumers(g, version):
    def workload():
        kinds = ["deployment.apps/demo-api"]
        if g.obj("startup-apps", "crd/rollouts.argoproj.io"):
            kinds.append("rollouts.argoproj.io/demo-api")
        found = [(k, obj) for k in kinds if (obj := g.obj("startup-apps", k))]
        require(len(found) < 2, "Both Deployment and Rollout exist for demo-api; finish the workload migration")
        return found[0] if found else None

    kind, obj = g.until("standard demo database consumer", workload)
    template = obj["spec"]["template"]
    require(any(e.get("name") == "DATABASE_URL" and
                e.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == "demo-api-postgresql" and
                e["valueFrom"]["secretKeyRef"].get("key") == "DATABASE_URL"
                for c in template["spec"]["containers"] for e in c.get("env", [])),
            "Demo workload does not consume the expected database Secret")
    if template.get("metadata", {}).get("annotations", {}).get(MARKER) != version:
        patch = {"metadata": {"resourceVersion": obj["metadata"]["resourceVersion"]},
                 "spec": {"template": {"metadata": {"annotations": {MARKER: version}}}}}
        g.k("-n", "startup-apps", "patch", kind, "--type=merge", "-p", json.dumps(patch))

    wait_for_replicas(g, kind, version)


def canary_progress(spec, status, connection):
    phase = status.get("phase", "Unknown")
    parts = [f"phase={phase}"]
    steps = spec.get("strategy", {}).get("canary", {}).get("steps", [])
    index = status.get("currentStepIndex")
    reasons = [c["reason"] for c in status.get("pauseConditions", []) if c.get("reason")]
    if spec.get("paused"):
        parts.append("spec.paused=true")
    if reasons:
        parts.append("pause=" + ",".join(reasons))
    if type(index) is int and 0 <= index < len(steps):
        step = steps[index]
        parts.append(f"canary step {index + 1}/{len(steps)}")
        weight = next((s["setWeight"] for s in reversed(steps[:index + 1]) if "setWeight" in s), None)
        if weight is not None:
            parts.append(f"target weight={weight}%")
        if "pause" in step:
            duration = step["pause"].get("duration")
            if duration is not None:
                parts.append(f"timed pause={duration}")
            elif phase == "Paused" and not spec.get("paused") and set(reasons) <= {"CanaryPauseStep"}:
                promote = shlex.join(["kubectl", "argo", "rollouts", "promote", "demo-api", *connection])
                parts.append(f"awaits manual promotion. After reviewing the Rollout and AnalysisRuns, run: {promote}")
        elif "analysis" in step:
            parts.append("inline analysis")
    analysis = status.get("canary", {}).get("currentStepAnalysisRunStatus") or {}
    if analysis:
        parts.append(f"AnalysisRun={analysis.get('name', '?')} ({analysis.get('status', 'Unknown')})")
    if status.get("abort"):
        parts.append("aborted")
    for condition in status.get("conditions", []):
        if condition.get("status") == "False" and condition.get("type") == "Progressing" and condition.get("reason"):
            parts.append(condition["reason"])
    return ", ".join(parts)


def wait_for_replicas(g, kind, version):
    rollout = kind.startswith("rollouts.")
    connection = ["--kubeconfig", str(g.path), "--context", g.context, "-n", "startup-apps"]
    started = last_print = time.monotonic()
    last = None

    def ready():
        nonlocal last, last_print
        latest = g.obj("startup-apps", kind) or {}
        spec = latest.get("spec", {})
        status = latest.get("status", {})
        desired = spec.get("replicas", 1)
        marked = spec.get("template", {}).get("metadata", {}).get("annotations", {}).get(MARKER) == version
        observed = marked and int(status.get("observedGeneration", 0)) >= int(latest["metadata"]["generation"])
        summary = f"ready={status.get('readyReplicas', 0)}/{desired}, updated={status.get('updatedReplicas', 0)}"
        if not observed:
            summary += ", waiting for the controller to observe the reconciled template"
        elif rollout:
            summary += ", " + canary_progress(spec, status, connection)
        now = time.monotonic()
        if last != summary or now - last_print >= 60:
            print(f"{kind} [{int(now - started)}s]: {summary}", flush=True)
            last, last_print = summary, now
        if observed and rollout and (status.get("abort") or status.get("phase") == "Degraded"):
            raise OpsError("Rollout controller reported failure")
        return (observed and desired > 0 and status.get("updatedReplicas") == desired
                and status.get("readyReplicas") == desired and status.get("replicas") == desired
                and (not rollout or (status.get("phase") == "Healthy" and not status.get("pauseConditions")
                                     and not spec.get("paused"))))

    try:
        g.until(f"{kind} replicas ready with the reconciled database credential (timeout {g.timeout}s)", ready)
    except OpsError as error:
        inspect = shlex.join(["kubectl", *connection, "describe", kind])
        detail = f"{error}\nLast observation: {last or 'unavailable'}\nInspect: {inspect}"
        if rollout:
            detail += "\nAnalysis: " + shlex.join(["kubectl", *connection, "get", "analysisruns.argoproj.io"])
        raise OpsError(detail) from error


def seed_database(g, out, adopt=None):
    external = wait_for_consumer(g)
    spec = external["spec"]
    key = out["external_secrets_secret_name"]
    require(key == g.context + "/demo-api/postgresql" and
            spec["secretStoreRef"] == {"kind": "SecretStore", "name": "aws-secrets-manager"} and
            spec["target"]["name"] == "demo-api-postgresql" and
            any(row["secretKey"] == "DATABASE_URL" and row["remoteRef"]["key"] == key and
                row["remoteRef"]["property"] == "DATABASE_URL" and row["remoteRef"].get("version") == "AWSCURRENT"
                for row in spec["data"]), "Unexpected demo ExternalSecret target or remote key")
    source = g.exists("data-platform", "secret/postgresql-baseline-app")
    encoded = source["data"]["fqdn-uri"]
    value = base64.b64decode(encoded, validate=True).decode()
    require(value.startswith("postgresql://"), "CNPG app Secret has no PostgreSQL URI")
    arn = out["external_secrets_secret_arn"]
    version = database_version(g, arn, key, value, adopt)
    ns = "startup-apps"
    refresh = str(time.time_ns())
    g.k("-n", ns, "annotate", EXTERNAL, "force-sync=" + refresh, "--overwrite")

    def synced():
        target = g.obj(ns, "secret/demo-api-postgresql") or {}
        return target.get("data", {}).get("DATABASE_URL") == encoded
    g.until("ESO target DATABASE_URL to match the current CNPG app Secret", synced)
    g.ready(ns, EXTERNAL)
    after = g.obj(ns, EXTERNAL) or {}
    if after.get("metadata", {}).get("annotations", {}).get("force-sync") == refresh:
        patch = [{"op": "test", "path": "/metadata/annotations/force-sync", "value": refresh},
                 {"op": "remove", "path": "/metadata/annotations/force-sync"}]
        g.k("-n", ns, "patch", EXTERNAL, "--type=json", "-p", json.dumps(patch))
    latest = g.obj("data-platform", "secret/postgresql-baseline-app") or {}
    require(latest.get("data", {}).get("fqdn-uri") == encoded, "CNPG credential changed during deployment; rerun deploy")
    labels = json.loads(g.aws("secretsmanager", "describe-secret", "--secret-id", arn))["VersionIdsToStages"]
    require("AWSCURRENT" in labels.get(version, []), "Demo credential changed during deployment; rerun deploy")
    refresh_consumers(g, version)


def reconcile_dns(g, out):
    hostname = out["demo_api_hostname"].rstrip(".")
    ns = "startup-apps"
    ingress = "ingress/demo-api"

    def endpoint():
        obj = g.obj(ns, ingress)
        if not obj:
            return None
        require(hostname in {rule.get("host") for rule in obj["spec"]["rules"]},
                "Terraform hostname differs from demo Ingress")
        endpoints = obj.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        return next((entry["hostname"] for entry in endpoints if entry.get("hostname")), None)

    dns = g.until("demo Ingress ALB hostname", endpoint)
    lbs = json.loads(g.aws("elbv2", "describe-load-balancers"))["LoadBalancers"]
    matches = [lb for lb in lbs if lb["DNSName"] == dns and lb["VpcId"] == out["vpc_id"]
               and lb["Type"] == "application"]
    require(len(matches) == 1, "Ingress ALB does not match the selected VPC")
    zone = out["route53_hosted_zone_id"]
    target = {"HostedZoneId": matches[0]["CanonicalHostedZoneId"], "DNSName": "dualstack." + dns,
              "EvaluateTargetHealth": True}
    records = json.loads(g.aws("route53", "list-resource-record-sets", "--hosted-zone-id", zone))["ResourceRecordSets"]
    existing = [item for item in records if item["Name"].rstrip(".") == hostname and item["Type"] == "A"]
    if existing:
        alias = existing[0].get("AliasTarget", {})
        require(len(existing) == 1 and not existing[0].get("SetIdentifier")
                and alias.get("HostedZoneId") == target["HostedZoneId"]
                and alias.get("DNSName", "").rstrip(".").removeprefix("dualstack.") == dns,
                "Existing DNS record points elsewhere; review ownership before changing it")
        return
    batch = {"Changes": [{"Action": "CREATE", "ResourceRecordSet": {
        "Name": hostname, "Type": "A", "AliasTarget": target}}]}
    result = json.loads(g.aws("route53", "change-resource-record-sets", "--hosted-zone-id", zone,
                              "--change-batch", json.dumps(batch)))
    g.aws("route53", "wait", "resource-record-sets-changed", "--id", result["ChangeInfo"]["Id"])


def complete(g, out, adopt=None):
    if out.get("database_mode", "cnpg") == "cnpg":
        seed_database(g, out, adopt)
    reconcile_dns(g, out)
