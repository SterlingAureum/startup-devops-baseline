"""Standard demo integration for the personal AWS dev GitOps stack."""
import base64
import json
import time
import uuid

from configuration import require


def seed_database(g, out):
    ns = "startup-apps"
    source = g.exists("data-platform", "secret/postgresql-baseline-app")
    pending = "externalsecrets.external-secrets.io/demo-api-postgresql"
    g.ready(ns, "crd/externalsecrets.external-secrets.io", "Established")
    external = g.exists(ns, pending)
    key = external["spec"]["data"][0]["remoteRef"]
    arn = out["external_secrets_secret_arn"]
    metadata = json.loads(g.aws("secretsmanager", "describe-secret", "--secret-id", arn))
    require(metadata["Name"] == out["external_secrets_secret_name"] == key["key"]
            and key["property"] == "DATABASE_URL" and not metadata.get("DeletedDate"),
            "Demo ExternalSecret and Terraform secret differ")
    if not any("AWSCURRENT" in stages for stages in metadata.get("VersionIdsToStages", {}).values()):
        value = base64.b64decode(source["data"]["fqdn-uri"], validate=True).decode()
        require(value.startswith("postgresql://"), "CNPG app Secret has no PostgreSQL URI")
        token = str(uuid.uuid5(uuid.NAMESPACE_URL, arn + "/" + source["metadata"]["uid"]))
        written = json.loads(g.aws(
            "secretsmanager", "put-secret-value", "--secret-id", arn, "--client-request-token", token,
            "--version-stages", "BASELINE_BOOTSTRAP", "--secret-string", "file:///dev/stdin",
            data=json.dumps({"DATABASE_URL": value}), private=True))
        # Omitting RemoveFromVersionId makes promotion fail if another writer already owns AWSCURRENT.
        if "AWSCURRENT" not in written.get("VersionStages", []):
            g.aws("secretsmanager", "update-secret-version-stage", "--secret-id", arn,
                  "--version-stage", "AWSCURRENT", "--move-to-version-id", token)
    # A rotated AWSCURRENT belongs to its operator. Refresh ESO without rewriting it.
    g.k("-n", ns, "annotate", pending, "force-sync=" + str(time.time_ns()), "--overwrite")
    g.ready(ns, pending)
    g.k("-n", ns, "annotate", pending, "force-sync-")
    target = g.exists(ns, "secret/demo-api-postgresql")
    require(target.get("data", {}).get("DATABASE_URL"), "ESO target Secret has no DATABASE_URL")


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

    dns = g.until("dev Ingress ALB hostname", endpoint)
    lbs = json.loads(g.aws("elbv2", "describe-load-balancers"))["LoadBalancers"]
    matches = [lb for lb in lbs if lb["DNSName"] == dns and lb["VpcId"] == out["vpc_id"]
               and lb["Type"] == "application"]
    require(len(matches) == 1, "Ingress ALB does not match the dev VPC")
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


def complete(g, out):
    seed_database(g, out)
    reconcile_dns(g, out)
