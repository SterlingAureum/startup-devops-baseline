"""Plan and apply the personal dev Terraform root in the initialized lifecycle session."""
import json
import subprocess

from configuration import require

PHASES = ["verify personal inputs and AWS caller", "initialize the selected backend in the default workspace",
          "plan the selected root with the inventory variables and check resource actions"]
APPLY = "apply the saved create/update plan when the cluster name is confirmed"


def check_plan(plan, g):
    require(not plan.get("errored") and plan.get("complete", True) and not plan.get("deferred_changes")
            and not plan.get("action_invocations"), "Terraform returned an incomplete plan or a separate action")
    cluster = None
    vpc = None
    creating_vpc = False
    for item in plan["resource_changes"]:
        change = item["change"]
        actions = change["actions"]
        allowed = (["no-op"], ["read"]) if item["mode"] == "data" else (["no-op"], ["create"], ["update"])
        require(actions in allowed and not change.get("importing"),
                f"Review dev infrastructure change outside create/update: {item['address']} {actions}")
        if item["address"] == "module.eks.aws_eks_cluster.this":
            cluster = change
        elif item["address"] == "module.vpc.aws_vpc.this":
            creating_vpc = actions == ["create"]
            vpc = (change.get("before") or {}).get("id")
    require(cluster and (cluster.get("after") or {}).get("name") == g.context,
            "Terraform plan does not select the expected EKS cluster")
    if cluster["actions"] == ["create"]:
        names = json.loads(g.aws("eks", "list-clusters"))["clusters"]
        require(g.context not in names, "Same-name EKS cluster already exists outside this creation plan; check the selected state")
    if creating_vpc:
        matches = json.loads(g.aws("ec2", "describe-vpcs", "--filters", "Name=tag:Name,Values=" + g.context + "-vpc"))["Vpcs"]
        require(not matches, "Same-name VPC already exists outside this creation plan; check the selected state")
    return vpc


def provision(g, terraform, tfenv, variables, plan_path, folder, confirm):
    print(f"Planning infrastructure for {g.context} with {variables}", flush=True)
    subprocess.run(terraform + ["plan", "-input=false", "-lock-timeout=60s", "-var-file=" + str(variables),
                                "-out=" + str(plan_path)], env=tfenv, check=True)
    raw = subprocess.run(terraform + ["show", "-json", str(plan_path)], env=tfenv, check=True,
                         stdout=subprocess.PIPE, text=True)
    vpc = check_plan(json.loads(raw.stdout), g)
    if vpc:
        # A provision retry must not resurrect a cluster halfway through network teardown.
        for path in folder.glob("*.json"):
            receipt = json.loads(path.read_text())
            require(receipt.get("vpc") != vpc or not receipt.get("cleaned") or receipt.get("complete"),
                    "Dev network teardown is pending for " + vpc + "; finish destroy before rebuilding")
    if confirm is None:
        print("Preview complete for " + g.context)
        return
    print("Applying the checked dev infrastructure plan", flush=True)
    subprocess.run(terraform + ["apply", "-input=false", "-lock-timeout=60s", str(plan_path)], env=tfenv, check=True)
    print("AWS dev infrastructure apply complete.", flush=True)
