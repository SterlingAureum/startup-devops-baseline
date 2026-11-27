"""Select one Terraform backend and inspect its current snapshot without migrating it."""
import json
from pathlib import Path
import re
import tempfile

from aws_database import BUCKET, SECRET, DURABLE, DEV_MOVES, original
from configuration import ROOT, OpsError, require


def lifecycle_directory(account, region, cluster):
    return Path.home() / ".local/state/startup-devops-baseline" / account / region / cluster


def backend_path(settings, base):
    key = "path" if settings["type"] == "local" else "config_file"
    return (base / Path(settings[key]).expanduser()).resolve()


def init_argument(settings, base):
    path = backend_path(settings, base)
    value = f"path={path}" if settings["type"] == "local" else str(path)
    return "-backend-config=" + value


def snapshot(path, stage, cluster, account, region):
    try:
        with path.open() as stream:
            state = json.load(stream)
    except (ValueError, UnicodeError) as error:
        raise OpsError("Invalid JSON in selected Terraform state") from error
    require(isinstance(state, dict) and state.get("version") == 4
            and isinstance(state.get("lineage"), str)
            and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", state["lineage"])
            and type(state.get("serial")) is int and state["serial"] >= 0
            and isinstance(state.get("resources"), list) and isinstance(state.get("outputs"), dict),
            "Expected a Terraform state snapshot with lineage and serial at the selected address")
    outputs = state["outputs"]
    for key, expected in (("environment_name", stage), ("cluster_name", cluster), ("eks_cluster_name", cluster)):
        if key in outputs:
            require(outputs[key]["value"] == expected, f"Selected state output {key} differs from {expected}")
    count = 0
    for resource in state["resources"]:
        if resource["mode"] != "managed":
            continue
        count += len(resource["instances"])
        for instance in resource["instances"]:
            attrs = instance["attributes"]
            if resource["type"] == "aws_eks_cluster":
                require(attrs.get("arn") == f"arn:aws:eks:{region}:{account}:cluster/{cluster}",
                        "State EKS ARN differs from selected account, region or cluster")
            if resource["type"] == "aws_vpc":
                require(attrs.get("owner_id") == account and attrs.get("tags", {}).get("Name") == cluster + "-vpc",
                        "State VPC owner or name differs from the selected target")
    result = {"status": "existing", "lineage": state["lineage"], "serial": state["serial"], "managed_instances": count}
    profile = outputs.get("database_mode", {}).get("value")
    if stage == "dev" and count:
        bucket = f"{cluster}-{account}-{region}-cnpg"
        storage = set()
        runtime = False
        cluster_mode = None
        for resource in state["resources"]:
            if resource["mode"] != "managed":
                continue
            raw = ".".join((resource.get("module", ""), resource["type"], resource.get("name", "")))
            addr = original(raw)
            if raw in DEV_MOVES and resource["instances"]:
                result["legacy_database_addresses"] = True
            for instance in resource["instances"]:
                attrs = instance["attributes"]
                if addr in DURABLE:
                    require("index_key" not in instance and not instance.get("deposed") and addr not in storage,
                            "Unexpected duplicate or indexed database storage in selected state")
                    storage.add(addr)
                    if addr == BUCKET:
                        require(attrs.get("id") == bucket,
                                "Retained database bucket differs from the selected dev target")
                    elif addr != SECRET:
                        require(attrs.get("bucket") == bucket, "Retained bucket configuration belongs to another bucket")
                    else:
                        require(attrs.get("name") == cluster + "/demo-api/postgresql" and
                                (attrs.get("arn") or "").startswith(f"arn:aws:secretsmanager:{region}:{account}:secret:"),
                                "Retained database secret differs from the selected dev target")
                        result["database_secret_arn"] = attrs["arn"]
                elif addr in DEV_MOVES:
                    runtime = True
                if resource["type"] == "aws_eks_cluster":
                    tags = attrs.get("tags") or {}
                    cluster_mode = tags.get("BaselineDatabaseMode", "cnpg")
                    if tags.get("BaselineDevCreationPlan"):
                        result["cluster_creation_marker"] = tags["BaselineDevCreationPlan"]
        if cluster_mode:
            result["cluster_database_mode"] = cluster_mode
        result.update(database_storage=sorted(storage), retained_only=len(storage) == count)
        # Interrupted apply can leave stale outputs. A live CNPG tag or its IAM resources
        # always wins over a stale 'none' when deciding whether removal would be safe.
        if runtime or cluster_mode == "cnpg":
            profile = "cnpg"
        elif cluster_mode:
            profile = cluster_mode
        elif profile is None and storage:
            profile = "cnpg"
    if profile is not None:
        require(profile in ("cnpg", "none"), "Unrecognized database mode in Terraform state")
        result["database_mode"] = profile
    return result


def local_snapshot(path, stage, cluster, account, region):
    try:
        return snapshot(path, stage, cluster, account, region)
    except FileNotFoundError:
        return {"status": "absent"}


def check_selected_state(g, report, operation):
    address = report["state_address"]
    print(f"Environment {report['environment']} | account {report['expected_account_id']} | "
          f"{report['region']} | cluster {g.context} | state {address}", flush=True)
    target = (report["stage"], g.context, report["expected_account_id"], report["region"])
    if report["declared_backend"] == "local":
        result = local_snapshot(Path(address), *target)
    else:
        # GetObject exercises both S3 and KMS read permissions before terraform init.
        with tempfile.TemporaryDirectory(prefix="baseline-state-") as tmp:
            copy = Path(tmp) / "snapshot"
            try:
                g.aws("s3api", "get-object", "--bucket", report["state_bucket"], "--key", report["backend_file_key"],
                      "--region", report["state_region"], "--expected-bucket-owner", report["expected_account_id"], str(copy))
            except OpsError as error:
                if "(NoSuchKey) when calling the GetObject operation" not in str(error):
                    raise
                result = {"status": "absent"}
            else:
                result = snapshot(copy, *target)
    print("Terraform state:", json.dumps(result), flush=True)
    mode = report.get("database_mode", "cnpg")
    if operation != "destroy" and mode == "none" and result.get("database_mode") == "cnpg":
        require(not result.get("managed_instances") or result.get("retained_only"),
                "Existing state uses database.mode=cnpg. Removing an installed database is unsupported.")
    if operation == "deploy" and result.get("database_mode") == "none" and mode == "cnpg":
        raise OpsError("Run plan then up to provision CNPG infrastructure before deploy")
    if result.get("retained_only") and operation in ("plan", "create", "up"):
        print("Rebuilding with retained database storage in the selected state.", flush=True)
    if result["status"] == "absent":
        root = ROOT / report["terraform_root"]
        # A private state may remain under the retired execution directory.
        roots = [root, root.with_name("dev-no-database")] if report["stage"] == "dev" else [root]
        for directory in roots:
            former_default = directory / "terraform.tfstate"
            if former_default != Path(address) and former_default.exists():
                raise OpsError(f"Selected state is absent but {former_default} exists. Review that state before initialization")
        require(operation in ("plan", "create", "up"), "Selected state is absent. Check its address before " + operation)
        clusters = json.loads(g.aws("eks", "list-clusters"))["clusters"]
        require(g.context not in clusters, "EKS already exists without selected state. Locate its original state")
        vpcs = json.loads(g.aws("ec2", "describe-vpcs", "--filters", "Name=tag:Name,Values=" + g.context + "-vpc"))["Vpcs"]
        require(not vpcs, "VPC already exists without selected state. Locate its original state")
    return result
