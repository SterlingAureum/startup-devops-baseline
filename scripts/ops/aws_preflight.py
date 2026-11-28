"""Offline preparation for the standard personal dev/test AWS environments."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import shutil
import tempfile
from urllib.parse import urlsplit

import yaml

from aws_state import backend_path, local_snapshot
from configuration import ROOT, OpsError, UniqueLoader, load_yaml, require


def read_inputs(path):
    try:
        import hcl2
    except ImportError:
        raise OpsError("Install scripts/ops/requirements-preflight.txt to read Terraform inputs") from None
    try:
        with path.open() as stream:
            data = json.load(stream) if path.suffix == ".json" else hcl2.load(stream)
    except FileNotFoundError:
        raise OpsError(f"Missing input file: {path}") from None
    except (OSError, ValueError, RuntimeError) as error:
        raise OpsError(f"Cannot read {path} ({type(error).__name__})") from None
    except Exception as error:
        # HCL parser diagnostics can include an excerpt of private operator input.
        raise OpsError(f"Invalid Terraform input: {path} ({type(error).__name__})") from None
    require(isinstance(data, dict), f"Expected an object in {path}")
    return data


def backend_type(root):
    primary = []
    overrides = []
    for path in sorted([*root.glob("*.tf"), *root.glob("*.tf.json")]):
        if path.name.startswith("."):
            continue
        stem = path.name.removesuffix(".json").removesuffix(".tf")
        override = stem == "override" or stem.endswith("_override")
        names = []
        blocks = read_inputs(path).get("terraform", [])
        for block in [blocks] if isinstance(blocks, dict) else blocks:
            backends = block.get("backend", [])
            for backend in [backends] if isinstance(backends, dict) else backends:
                names.extend(backend)
            if "cloud" in block:
                names.append("cloud")
        require(len(names) <= 1, f"Multiple backend declarations in {path.name}")
        if override:
            overrides.extend(names)
        else:
            primary.extend(names)
    require(len(primary) <= 1, f"Multiple backend declarations under {root.name}")
    return (overrides or primary or ["local"])[-1]


def execution_root(root, backend, tmp, *, legacy=False):
    """Prepare a private S3 root or omit address moves for legacy targeted destroy."""
    if backend["type"] == "local" and not legacy:
        return root
    actual = Path(tempfile.mkdtemp(dir=tmp)) / "infra/terraform/aws/environments" / root.name
    actual.mkdir(parents=True)
    (actual.parents[1] / "modules").symlink_to(root.parents[1] / "modules", target_is_directory=True)
    for item in root.iterdir():
        if legacy and item.name == "database-moves.tf":
            continue
        if item.name == ".terraform.lock.hcl":
            shutil.copyfile(item, actual / item.name)
        elif item.name.endswith((".tf", ".tf.json", ".tfvars", ".tfvars.json")):
            (actual / item.name).symlink_to(item)
    if backend["type"] == "s3" and backend_type(root) == "local":
        dest = actual / "s3_override.tf"
        require(not dest.is_symlink(), f"Conflicting override in {root}")
        shutil.copyfile(root / "s3_override.tf.example", dest)
    require(backend_type(actual) == backend["type"], "Active Terraform override conflicts with inventory backend")
    return actual


def implicit_inputs(root):
    return [path for path in [root / "terraform.tfvars", root / "terraform.tfvars.json",
                              *sorted([*root.glob("*.auto.tfvars"), *root.glob("*.auto.tfvars.json")])]
            if path.is_file()]


def deployment_inputs(root, selected):
    declarations = read_inputs(root / "variables.tf")["variable"]
    values = {key: spec["default"] for block in declarations for key, spec in block.items() if "default" in spec}
    for path in implicit_inputs(root):
        values.update(read_inputs(path))
    values.update(read_inputs(selected))
    return values


def cluster_name(values, stage, region):
    require(values["environment"] == stage and values["aws_region"] == region, "Terraform environment/region mismatch")
    project = values["project_name"]
    require(isinstance(project, str), "Terraform project_name must be a string")
    cluster = f"{project}-{stage}"
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", cluster), "Invalid physical EKS cluster name")
    return cluster


def local_file(value, config_dir):
    require(isinstance(value, str) and value, "Personal preflight needs terraform.variables_file")
    return config_dir / Path(value).expanduser()


def kustomize(path):
    source = (ROOT / path).resolve()
    require(source.is_relative_to(ROOT) and source.is_dir(), "Missing repository Kustomize directory")
    result = subprocess.run(["kubectl", "kustomize", str(source)], check=True, text=True,
                            capture_output=True, timeout=90)
    return list(yaml.load_all(result.stdout, Loader=UniqueLoader))


def check_private_vars(values, account, cluster):
    require(values.get("enable_github_actions_runtime_identity") is True,
            "Runtime access entry disabled in tfvars; review enable_github_actions_runtime_identity")
    require(values.get("github_actions_runtime_role_arn") ==
            f"arn:aws:iam::{account}:role/{cluster}-github-runtime-read-role",
            "Use the matching persistent role output from runtime-identities")
    public, private = values["eks_endpoint_public_access"], values["eks_endpoint_private_access"]
    require(type(public) is bool and type(private) is bool and (public or private),
            "Select a reachable EKS endpoint")
    if public:
        cidrs = values["eks_public_access_cidrs"]
        try:
            valid = isinstance(cidrs, list) and cidrs and all(
                isinstance(x, str) and ipaddress.IPv4Network(x, strict=False).prefixlen > 0 for x in cidrs)
        except ValueError:
            valid = False
        require(valid, "Set eks_public_access_cidrs in the selected private tfvars to restricted IPv4 CIDRs (for one client, its egress IPv4/32)")


def policy_cidrs(spec, direction, port):
    peer_field = "to" if direction == "egress" else "from"
    cidrs = set()
    for rule in spec.get(direction, []):
        if not any(item.get("port") == port for item in rule.get("ports", [])):
            continue
        for peer in rule.get(peer_field, []):
            block = peer.get("ipBlock")
            # The recovery policy has a separate public HTTPS rule with private ranges excluded.
            if block and not block.get("except"):
                cidrs.add(block["cidr"])
    return cidrs


def check_network_policies(children, name, values, *, database_mode="cnpg"):
    """Compare the standard AWS policy address groups with the effective Terraform inputs."""
    service = ipaddress.IPv4Network(values["eks_service_ipv4_cidr"])
    require(service.num_addresses > 10, "eks_service_ipv4_cidr must contain the API and DNS Service addresses")
    private = set(values["private_subnet_cidrs"])
    public = set(values["public_subnet_cidrs"])
    api = private | {f"{service[1]}/32"}
    rules = {
        "data-platform": [
            ("allow-cnpg-to-kubernetes-api", "egress", 443, api),
            ("allow-dns-egress", "egress", 53, {f"{service[10]}/32"}),
            ("allow-postgresql-baseline-join-egress", "egress", 443, api),
            ("allow-postgresql-baseline-join-egress", "egress", 5432, {str(service)}),
            ("allow-cnpg-to-postgresql-rw-service", "egress", 5432, {str(service)}),
            ("allow-kubernetes-api-to-cnpg-status", "ingress", 8000, private),
            ("allow-cnpg-to-barman-plugin", "egress", 9090, {str(service)}),
            ("allow-cnpg-full-recovery-egress", "egress", 443, api),
        ],
        "startup-apps": [("allow-alb-to-demo-api", "ingress", 8080, public)],
    }
    if database_mode == "none":
        del rules["data-platform"]
    for namespace, checks in rules.items():
        application = f"{namespace}-network-policy-{name}"
        require(application in children, f"Missing network policy Application: {application}")
        path = children[application]["spec"]["source"]["path"]
        policies = {doc["metadata"]["name"]: doc["spec"] for doc in kustomize(path)
                    if doc and doc["kind"] == "NetworkPolicy" and doc["metadata"].get("namespace") == namespace}
        for policy, direction, port, expected in checks:
            actual = policy_cidrs(policies.get(policy, {}), direction, port)
            require(actual == expected,
                    f"Network CIDR mismatch for {namespace}/{policy} ({direction} port {port}). "
                    f"Terraform expects {sorted(expected)}, {path} renders {sorted(actual)}. "
                    "Align the GitOps policy with the selected environment network.")


def check_bindings(objects, namespace, group, permissions):
    roles = {obj["metadata"]["name"]: obj for obj in objects
             if obj["kind"] == "Role" and obj["metadata"]["namespace"] == namespace}
    rules = []
    for obj in objects:
        if obj["kind"] != "RoleBinding" or obj["metadata"]["namespace"] != namespace:
            continue
        ref = obj["roleRef"]
        if ref.get("kind") == "Role" and any(s.get("kind") == "Group" and s.get("name") == group for s in obj["subjects"]):
            rules.extend(roles.get(ref["name"], {}).get("rules", []))
    for api, resource, verb in permissions:
        require(any(api in rule["apiGroups"] and resource in rule["resources"] and verb in rule["verbs"]
                    and not rule.get("resourceNames") for rule in rules),
                f"Missing runtime group permission: {namespace} {verb} {resource}")


def runtime_target(name):
    workflow = yaml.load((ROOT / ".github/workflows/delivery-verify.yaml").read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["verify"]
    token = "${{ inputs.environment }}"
    labels = [value.replace(token, name) for value in job["runs-on"]]
    environment = job["environment"]["name"].replace(token, name)
    permissions = job.get("permissions", workflow.get("permissions", {}))
    require(name in labels and {"self-hosted", "trusted-runtime"} <= set(labels)
            and environment == name + "-runtime" and permissions.get("id-token") == "write",
            "Runtime workflow differs from the environment runner/OIDC contract")
    return environment, labels


def inspect_infrastructure(selected, env, config_path, personal):
    """Read the physical target and state settings shared by provisioning and teardown."""
    name = selected.delivery_environment
    short = selected.stage
    root = selected.terraform_root
    aws, tf = env["aws"], env["terraform"]
    config_dir = config_path.expanduser().resolve().parent
    variables = local_file(tf.get("variables_file"), config_dir) if personal else root / "terraform.tfvars.example"
    declared_backend = backend_type(root)
    settings = tf["backend"]
    require(declared_backend in ("local", "s3"), f"Unsupported backend {declared_backend}")
    if settings["type"] == "s3" and declared_backend == "local" and (root / "s3_override.tf.example").is_file():
        declared_backend = "s3"
    require(settings["type"] == declared_backend,
            f"{name} root declares {declared_backend} state. Configure terraform.backend for this type; "
            "changing the inventory does not migrate state")
    state_info = {"state_status": "not-checked"}
    if declared_backend == "s3":
        path = backend_path(settings, config_dir) if personal else root.parents[1] / "backend-config" / f"{short}.s3.tfbackend.example"
        require(path.is_file(), f"Missing input file: {path}")
        state_info["backend_config_file"] = str(path)
    else:
        path = backend_path(settings, config_dir)
        state_info["state_address"] = str(path)
    values = deployment_inputs(root, variables)
    cluster = cluster_name(values, short, aws["region"])
    if personal:
        if declared_backend == "local":
            observed = local_snapshot(path, short, cluster, aws["expected_account_id"], aws["region"])
            state_info.update(state_status=observed["status"])
            if observed["status"] == "existing":
                state_info["state_snapshot"] = observed
        if "role_arn" in aws:
            require(re.fullmatch(r"arn:aws:iam::" + aws["expected_account_id"] + r":role/[A-Za-z0-9+=,.@_/-]+", aws["role_arn"]),
                    "Operator role ARN differs from the personal target account")
    report = {"environment": selected.inventory_name, "stage": short, "cluster": cluster,
              "terraform_root": tf["root"], "expected_account_id": aws["expected_account_id"],
              "region": aws["region"], "declared_backend": declared_backend, **state_info}
    return report, values


def inspect(selected, env, config_path, personal=False):
    report, values = inspect_infrastructure(selected, env, config_path, personal)
    cluster = report["cluster"]
    root = selected.terraform_root
    name = selected.delivery_environment
    cfg = selected.catalog
    target = cfg["environments"][name]
    mode = env.get("database", {}).get("mode", "cnpg")
    manifest = selected.gitops_root
    require(not {"retained_database_bucket", "retained_database_secret", "database_creation_marker"}.intersection(values),
            "Select database.mode in the inventory. The CLI derives database retention and ownership from state.")
    sizes = {k: values["eks_node_" + k + "_size"] for k in ("min", "desired", "max")}
    require(all(type(v) is int for v in sizes.values()) and 0 <= sizes["min"] <= sizes["desired"] <= sizes["max"]
            and sizes["max"] >= 1, "Check min/desired/max node capacity in the selected var-file")
    if personal:
        check_private_vars(values, env["aws"]["expected_account_id"], cluster)
    blockers = []
    if not personal:
        if values.get("enable_github_actions_runtime_identity") is not True:
            blockers.append("Runtime EKS access entry disabled in the example inputs")
        if values.get("eks_endpoint_public_access") and not values.get("eks_public_access_cidrs"):
            blockers.append("Public endpoint needs restricted CIDRs in the personal inputs")

    root_app = load_yaml((ROOT / manifest).read_text())
    spec = root_app["spec"]
    src = spec["source"]
    require(src["path"] == str(Path(manifest).parent) and src["targetRevision"] == cfg["base_branch"]
            and spec["destination"] == {"server": "https://kubernetes.default.svc", "namespace": "argocd"},
            "Unexpected root Application source or destination")
    if "gitops" in env:
        configured = env["gitops"]
        require(configured["repository"] == src["repoURL"]
                and configured["root_application"] == root_app["metadata"]["name"]
                and configured.get("revision") in (None, src["targetRevision"]) and not configured.get("parameters"),
                "Inventory GitOps settings differ from the selected AWS root")
    url = urlsplit(src["repoURL"])
    repo = url.path.strip("/").removesuffix(".git")
    require(url.scheme == "https" and url.netloc == "github.com" and re.fullmatch(r"[\w.-]+/[\w.-]+", repo),
            "Expected a GitHub repository URL in the AWS root")
    require(urlsplit(target["url"]).hostname == values["demo_api_hostname"], "Terraform hostname differs from delivery URL")
    children = {d["metadata"]["name"]: d for d in kustomize(src["path"]) if d and d["kind"] == "Application"}
    require(target["application"] in children, "Runtime target Application is absent from the overlay")
    if mode == "none":
        helm = children[target["application"]]["spec"]["source"]["helm"]
        require(helm.get("valuesObject", {}).get("database", {}).get("enabled") is False
                and not any(p["name"].startswith("database.") for p in helm.get("parameters", []))
                and not {"cloudnative-pg", "postgresql-baseline", "barman-cloud-plugin",
                         "external-secrets-startup-apps"}.intersection(children),
                "Database-free GitOps profile contains database dependencies")
    check_network_policies(children, name, values, database_mode=mode)
    alb = children["aws-load-balancer-controller"]["spec"]["source"]["helm"]["valuesObject"]
    require((alb["clusterName"], alb["region"], alb["vpcId"]) == (cluster, report["region"], "__VPC_ID__"),
            "Load balancer controller wiring differs from the bootstrap contract")
    require("RespectIgnoreDifferences=true" in spec["syncPolicy"]["syncOptions"] and any(
        item.get("kind") == "Application" and item.get("name") == "aws-load-balancer-controller"
        and "/spec/source/helm/valuesObject/vpcId" in item.get("jsonPointers", []) for item in spec["ignoreDifferences"]),
        "Root must preserve the bootstrapped VPC ID")
    rbac = children[f"runtime-qualification-rbac-{name}"]["spec"]["source"]
    require((rbac["repoURL"], rbac["targetRevision"]) == (src["repoURL"], src["targetRevision"]),
            "Runtime RBAC Application points to another source")
    objects = kustomize(rbac["path"])
    group = read_inputs(root.parents[1] / "modules/github-actions-runtime-identity/main.tf")["locals"][0]["kubernetes_group"]
    check_bindings(objects, "argocd", group, [("argoproj.io", "applications", "get")])
    check_bindings(objects, cfg["application"]["namespace"], group, [
        ("argoproj.io", "rollouts", "get"), ("apps", "deployments", "get"), ("", "pods", "list"),
        ("argoproj.io", "analysisruns", "list")])
    check_bindings(objects, cfg["runtime"]["prometheus_namespace"], group, [
        ("", "services", "get"), ("", "pods", "list"), ("", "pods/portforward", "create")])
    identities = root.parents[1] / "runtime-identities"
    example_repo = read_inputs(identities / "terraform.tfvars.example")["github_repository"]
    require(repo == example_repo, "Root GitHub repository differs from the runtime-identities declaration example")
    gh_env, labels = runtime_target(name)
    return {**report, "terraform_execution_root": str(root.relative_to(ROOT)), "database_mode": mode, "driver": "aws", "delivery_environment": name,
            "scope": "personal-files" if personal else "repository-examples",
            "offline_result": "passed", "live_checks": "pending",
            "runtime_identities_backend": backend_type(identities), "live_blockers": blockers, "gitops_root": manifest,
            "application": target["application"], "runtime_environment": gh_env,
            "runner_labels": labels,
            "expected_oidc_subject": f"repo:{repo}:environment:{gh_env}", "eks_group": group,
            "runtime_access_requested": values["enable_github_actions_runtime_identity"],
            "node_group": sizes,
            "bootstrap_vpc_id": "pending Terraform output"}
