"""Select one Terraform backend and inspect its current snapshot without migrating it."""
import json
from pathlib import Path
import re
import tempfile

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


def execution_root(root, mode):
    if mode == "none":
        require(root.name == "dev", "Database-free Terraform composition requires the dev root")
        return root.with_name("dev-no-database")
    require(mode == "cnpg", "Unrecognized database mode in selected state or inventory")
    return root


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
    profile = outputs.get("database_mode", {}).get("value")
    if stage == "dev" and count and profile is None:
        # An interrupted first apply may precede outputs. The EKS tag records the selected composition.
        for resource in state["resources"]:
            if resource["mode"] == "managed" and resource["type"] == "aws_eks_cluster" and resource["instances"]:
                tags = resource["instances"][0]["attributes"].get("tags") or {}
                profile = tags.get("BaselineDatabaseMode", "cnpg")
                break
            if resource.get("module") in ("module.cnpg_backup", "module.external_secrets") and resource["instances"]:
                profile = "cnpg"
                break
    result = {"status": "existing", "lineage": state["lineage"], "serial": state["serial"], "managed_instances": count}
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
    if operation != "destroy" and result.get("managed_instances") and result.get("database_mode"):
        require(result["database_mode"] == report.get("database_mode", "cnpg"),
                f"Existing state uses database.mode={result['database_mode']}. "
                "Review retention and destroy the old environment before selecting a different profile.")
    if result["status"] == "absent":
        root = ROOT / report["terraform_root"]
        roots = [root, execution_root(root, "none")] if report["stage"] == "dev" else [root]
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
