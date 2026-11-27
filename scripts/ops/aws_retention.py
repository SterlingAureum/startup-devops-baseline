"""Read metadata for the two data stores of one standard personal AWS environment."""
import json
from dataclasses import dataclass

from aws_database import BUCKET, SECRET, DURABLE, original
from configuration import OpsError, require


@dataclass(frozen=True)
class Observation:
    name: str
    status: str
    marker: str | None = None
    deletion_date: str | None = None


def observe(g, kind, account, region, *, expected_arn=None):
    if kind == BUCKET:
        name = f"{g.context}-{account}-{region}-cnpg".lower()
        try:
            data = json.loads(g.aws("s3api", "get-bucket-tagging", "--bucket", name,
                                    "--region", region, "--expected-bucket-owner", account))
        except OpsError as error:
            if "(NoSuchBucket) when calling the GetBucketTagging operation" in str(error):
                return Observation(name, "absent")
            if "(NoSuchTagSet) when calling the GetBucketTagging operation" in str(error):
                return Observation(name, "present")
            raise
        require(isinstance(data.get("TagSet"), list), f"Unrecognized S3 metadata for {name}")
        tags = data["TagSet"]
    else:
        name = g.context + "/demo-api/postgresql"
        arn_prefix = f"arn:aws:secretsmanager:{region}:{account}:secret:{name}-"
        if expected_arn is not None:
            require(isinstance(expected_arn, str) and expected_arn.startswith(arn_prefix),
                    f"Secret identity differs from selected environment: {name}")
        try:
            data = json.loads(g.aws("secretsmanager", "describe-secret", "--secret-id", name, "--region", region))
        except OpsError as error:
            if "(ResourceNotFoundException) when calling the DescribeSecret operation" in str(error):
                return Observation(name, "absent")
            raise
        arn = data.get("ARN", "")
        require(data.get("Name") == name and arn.startswith(arn_prefix)
                and (expected_arn is None or arn == expected_arn), f"Secret identity differs from state: {name}")
        if data.get("DeletedDate"):
            return Observation(name, "scheduled for deletion", deletion_date=str(data["DeletedDate"]))
        tags = data.get("Tags", [])
    marker = next((tag["Value"] for tag in tags if tag["Key"] == "BaselineDevCreationPlan"), None)
    return Observation(name, "present", marker)


def live_dev_storage(g, report, summary):
    storage = set(summary.get("database_storage", []))
    for kind, group in ((BUCKET, DURABLE - {SECRET}), (SECRET, {SECRET})):
        if not storage.intersection(group):
            continue
        item = observe(g, kind, report["expected_account_id"], report["region"],
                       expected_arn=summary.get("database_secret_arn"))
        require(item.status != "scheduled for deletion",
                f"{item.name} is scheduled for deletion on {item.deletion_date}. Review before rebuilding.")
        if item.status == "absent":
            print(f"AWS absent: {item.name}. Refresh stale state during checked apply; no recreation in none mode.")
            storage.difference_update(group)
        else:
            require(kind in storage, f"Missing state anchor for live storage: {item.name}")
            print(f"AWS present: keep {item.name} managed in the selected state.")
    return dict(summary, database_storage=sorted(storage))


def retention_reason(attrs, owner, retain, kind):
    if retain:
        return "retain-backups policy"
    marker = (attrs.get("tags") or {}).get("BaselineDevCreationPlan")
    if not marker:
        return "creation marker missing in state"
    if not owner:
        return "cluster creation marker unavailable"
    if marker != owner:
        return "belongs to an earlier creation"
    if kind == BUCKET and attrs.get("force_destroy") is not True:
        return "bucket force_destroy is disabled"
    return "owned by this cluster generation"


def report_storage(g, aws, state, targets, keep, owner, retain):
    """Report physical stores once even though the bucket has several Terraform addresses."""
    attrs = {}
    bucket_name = f"{g.context}-{aws['expected_account_id']}-{aws['region']}-cnpg".lower()
    for row in state["resources"]:
        if row["mode"] == "managed" and row["instances"]:
            key = original(".".join((row.get("module", ""), row["type"], row["name"])))
            if key not in DURABLE:
                continue
            require(len(row["instances"]) == 1 and key not in attrs and
                    not {"index_key", "deposed"}.intersection(row["instances"][0]),
                    "Unexpected database instance in state: " + key)
            attrs[key] = row["instances"][0]["attributes"]
            if key == SECRET:
                require(attrs[key].get("name") == g.context + "/demo-api/postgresql" and attrs[key].get("arn"),
                        "Unexpected database secret in selected state")
            else:
                field = "id" if key == BUCKET else "bucket"
                require(attrs[key].get(field) == bucket_name, "Unexpected backup bucket in selected state")
    missing = set()
    for kind, group in ((BUCKET, DURABLE - {SECRET}), (SECRET, {SECRET})):
        addresses = {a for a in targets | keep if original(a) in group}
        if not addresses:
            continue
        stored = attrs.get(kind, {})
        live = observe(g, kind, aws["expected_account_id"], aws["region"], expected_arn=stored.get("arn") if kind == SECRET else None)
        delete = bool(addresses & targets)
        if live.status == "absent":
            stale = addresses & keep
            print(f"AWS absent: {live.name}." + (f" Stale state addresses: {len(stale)}." if stale else ""))
            missing.update(stale)
        elif live.deletion_date:
            print(f"AWS scheduled for deletion: {live.name} on {live.deletion_date}.")
        elif delete:
            require(owner and live.marker == owner, f"Live creation marker changed for {live.name}. Review before deletion.")
            print(f"AWS present, planned deletion: {live.name}")
        else:
            print(f"AWS present, kept: {live.name} ({retention_reason(stored, owner, retain, kind)}).")
    return missing
