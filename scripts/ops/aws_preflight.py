"""Offline preparation for the standard personal dev/test AWS environments."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import yaml

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
    names = []
    for path in sorted(root.glob("*.tf")):
        for block in read_inputs(path).get("terraform", []):
            for backend in block.get("backend", []):
                names.extend(backend)
            if "cloud" in block:
                names.append("cloud")
    require(len(names) <= 1, f"Multiple backend declarations under {root.name}")
    return names[0] if names else "local"


def deployment_inputs(root, selected):
    declarations = read_inputs(root / "variables.tf")["variable"]
    values = {key: spec["default"] for block in declarations for key, spec in block.items() if "default" in spec}
    implicit = [root / "terraform.tfvars", root / "terraform.tfvars.json",
                *sorted([*root.glob("*.auto.tfvars"), *root.glob("*.auto.tfvars.json")])]
    for path in implicit:
        if path.is_file():
            values.update(read_inputs(path))
    values.update(read_inputs(selected))
    return values


def local_file(value, config_dir):
    require(isinstance(value, str) and value, "Personal preflight needs variables_file and backend_file")
    return config_dir / Path(value).expanduser()


def kustomize(path):
    source = (ROOT / path).resolve()
    require(source.is_relative_to(ROOT) and source.is_dir(), "Missing repository Kustomize directory")
    result = subprocess.run(["kubectl", "kustomize", str(source)], check=True, text=True,
                            capture_output=True, timeout=90)
    return list(yaml.load_all(result.stdout, Loader=UniqueLoader))


def check_backend(backend, environment, aws, personal):
    require(backend.get("key") == f"environments/{environment}/terraform.tfstate",
            "Unexpected backend key for the selected standard environment")
    require(backend.get("use_lockfile") is True and backend.get("encrypt") is True,
            "The standard backend requires native locking and encryption")
    for key in ("bucket", "region", "kms_key_id"):
        require(isinstance(backend.get(key), str) and backend[key], f"Backend requires {key}")
    if personal:
        require(backend.get("allowed_account_ids") == [aws["expected_account_id"]],
                "Backend allowed_account_ids must match the inventory for the personal single-account profile")
        require(not backend["bucket"].startswith("replace-") and
                re.fullmatch(r"arn:aws:kms:" + re.escape(backend["region"]) + ":" +
                             aws["expected_account_id"] + r":key/[A-Za-z0-9-]+", backend["kms_key_id"]),
                "Supply the actual state bucket and matching KMS key ARN from state-bootstrap")


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


def inspect(name, env, config_path, personal=False):
    require(name in ("aws-dev", "aws-test"), "AWS preflight supports the standard aws-dev and aws-test entries")
    short = name.removeprefix("aws-")
    aws, tf = env["aws"], env["terraform"]
    root = ROOT / "infra/terraform/aws/environments" / short
    require((ROOT / tf["root"]).resolve() == root, "Terraform root differs from selected environment")
    config_dir = config_path.expanduser().resolve().parent
    variables = local_file(tf.get("variables_file"), config_dir) if personal else root / "terraform.tfvars.example"
    backend_path = (local_file(tf.get("backend_file"), config_dir) if personal else
                    root.parents[1] / "backend-config" / f"{short}.s3.tfbackend.example")
    declared_backend = backend_type(root)
    blockers = []
    if declared_backend != "s3":
        message = f"{name} root declares {declared_backend} state; its S3 backend file cannot select that backend"
        require(not personal and name == "aws-test" and declared_backend == "local", message)
        blockers.append(message)
    backend = read_inputs(backend_path)
    check_backend(backend, short, aws, personal)
    values = deployment_inputs(root, variables)
    require(values["environment"] == short and values["aws_region"] == aws["region"], "Terraform environment/region mismatch")
    sizes = {k: values["eks_node_" + k + "_size"] for k in ("min", "desired", "max")}
    require(all(type(v) is int for v in sizes.values()) and 0 <= sizes["min"] <= sizes["desired"] <= sizes["max"]
            and sizes["max"] >= 1, "Check min/desired/max node capacity in the selected var-file")
    cluster = f"{values['project_name']}-{short}"
    if personal:
        if "role_arn" in aws:
            require(re.fullmatch(r"arn:aws:iam::" + aws["expected_account_id"] + r":role/[A-Za-z0-9+=,.@_/-]+", aws["role_arn"]),
                    "Operator role ARN differs from the personal target account")
        check_private_vars(values, aws["expected_account_id"], cluster)

    if not personal:
        if values.get("enable_github_actions_runtime_identity") is not True:
            blockers.append("Runtime EKS access entry disabled in the example inputs")
        if values.get("eks_endpoint_public_access") and not values.get("eks_public_access_cidrs"):
            blockers.append("Public endpoint needs restricted CIDRs in the personal inputs")

    cfg = json.loads((ROOT / "delivery/standard/config.json").read_text())
    target = cfg["environments"][name]
    manifest = f"clusters/aws/overlays/{short}/root-app.yaml"
    require(target["root_manifest"] == manifest, "Delivery selects another GitOps root")
    root_app = load_yaml((ROOT / manifest).read_text())
    spec = root_app["spec"]
    src = spec["source"]
    require(src["path"] == str(Path(manifest).parent) and src["targetRevision"] == cfg["base_branch"]
            and spec["destination"] == {"server": "https://kubernetes.default.svc", "namespace": "argocd"},
            "Unexpected root Application source or destination")
    if "gitops" in env:
        configured = env["gitops"]
        require(configured["repository"] == src["repoURL"] and configured["root_manifest"] == manifest
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
    alb = children["aws-load-balancer-controller"]["spec"]["source"]["helm"]["valuesObject"]
    require((alb["clusterName"], alb["region"], alb["vpcId"]) == (cluster, aws["region"], "__VPC_ID__"),
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
    return {"environment": name, "scope": "personal-files" if personal else "repository-examples",
            "offline_result": "passed", "live_checks": "pending", "terraform_root": tf["root"],
            "declared_backend": declared_backend, "backend_file_key": backend["key"],
            "runtime_identities_backend": backend_type(identities), "live_blockers": blockers, "cluster": cluster, "region": aws["region"], "gitops_root": manifest,
            "application": target["application"], "runtime_environment": gh_env,
            "runner_labels": labels,
            "expected_oidc_subject": f"repo:{repo}:environment:{gh_env}", "eks_group": group,
            "runtime_access_requested": values["enable_github_actions_runtime_identity"],
            "node_group": sizes,
            "bootstrap_vpc_id": "pending Terraform output"}
