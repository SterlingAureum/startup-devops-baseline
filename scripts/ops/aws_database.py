"""Personal dev database resource addresses and compatibility with the original CNPG modules."""
BUCKET = "module.cnpg_backup.aws_s3_bucket.this"
SECRET = "module.external_secrets.aws_secretsmanager_secret.this"
BUCKET_TYPES = {
    "aws_s3_bucket", "aws_s3_bucket_lifecycle_configuration", "aws_s3_bucket_ownership_controls",
    "aws_s3_bucket_policy", "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration", "aws_s3_bucket_versioning",
}
DURABLE = {"module.cnpg_backup." + kind + ".this" for kind in BUCKET_TYPES} | {SECRET}
ACCESS_TYPES = {"aws_iam_role", "aws_iam_policy", "aws_iam_role_policy_attachment"}
DEV_MOVES = {}
for module in ("cnpg_backup", "external_secrets"):
    for kind in ACCESS_TYPES | (BUCKET_TYPES if module == "cnpg_backup" else {"aws_secretsmanager_secret"}):
        part = "access" if kind in ACCESS_TYPES else "storage"
        DEV_MOVES[f"module.{module}.{kind}.this"] = f"module.{module}_{part}[0].{kind}.this"
ORIGINAL = {new: old for old, new in DEV_MOVES.items()}


def original(address):
    return ORIGINAL.get(address, address)


def dev_variables(stage, mode, summary):
    if stage != "dev":
        return []
    storage = summary.get("database_storage", [])
    arguments = [f"-var=database_mode={mode}"]
    for address, name in ((BUCKET, "bucket"), (SECRET, "secret")):
        present = "true" if address in storage else "false"
        arguments.append(f"-var=retained_database_{name}={present}")
    if summary.get("cluster_creation_marker"):
        arguments.append("-var=database_creation_marker=" + summary["cluster_creation_marker"])
    return arguments
