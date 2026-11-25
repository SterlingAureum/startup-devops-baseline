"""Release EKS-created dependencies in the selected VPC after cluster deletion."""
import json
import re

from configuration import OpsError, require


def tags(entries):
    return {entry["Key"]: entry["Value"] for entry in entries}


def release_network(g, journal, state):
    vpc = journal["vpc"]
    require(journal.get("cleaned") and g.context not in json.loads(g.aws("eks", "list-clusters"))["clusters"],
            "Network cleanup requires completed Kubernetes cleanup and an absent selected cluster")
    scope = "Name=vpc-id,Values=" + vpc

    def inventory(action, key, *filters):
        return json.loads(g.aws("ec2", action, "--filters", scope, *filters))[key]

    # NAT ENIs will be released by the reviewed Terraform network plan.
    nat_ids = {i["attributes"]["id"] for r in state["resources"]
               if r.get("module") == "module.vpc" and r["type"] == "aws_nat_gateway" and r["mode"] == "managed"
               for i in r["instances"]}
    nat_enis = set()
    if nat_ids:
        gateways = json.loads(g.aws("ec2", "describe-nat-gateways", "--filter", scope,
                                    "Name=nat-gateway-id,Values=" + ",".join(sorted(nat_ids))))["NatGateways"]
        nat_enis = {a.get("NetworkInterfaceId") for gw in gateways for a in gw["NatGatewayAddresses"]}

    def remove(action, option, identifier, missing):
        try:
            g.aws("ec2", action, option, identifier)
        except OpsError as error:
            if "(" + missing + ")" not in str(error):
                raise OpsError(f"Network cleanup stopped at {identifier}: {error}") from error
        print("Released cluster network dependency: " + identifier, flush=True)

    for eni in inventory("describe-network-interfaces", "NetworkInterfaces"):
        identifier = eni["NetworkInterfaceId"]
        if identifier in nat_enis:
            continue
        labels = tags(eni.get("TagSet", []))
        node = labels.get("node.k8s.amazonaws.com/instance_id", "")
        require(eni.get("VpcId") == vpc and eni.get("InterfaceType") == "interface"
                and eni.get("Status") == "available" and eni.get("RequesterManaged") is False
                and not eni.get("Attachment") and re.fullmatch(r"i-[a-f0-9]+", node)
                and eni.get("Description") == "aws-K8S-" + node
                and labels.get("eks:eni:owner") == "amazon-vpc-cni"
                and labels.get("cluster.k8s.amazonaws.com/name") == g.context,
                f"Review ENI {identifier} in {eni.get('SubnetId')}: {eni.get('Status')} {eni.get('Description')}")
        rows = json.loads(g.aws("ec2", "describe-instances", "--filters", "Name=instance-id,Values=" + node))
        instances = [i for r in rows["Reservations"] for i in r["Instances"]]
        require(len(instances) == 1 and instances[0]["InstanceId"] == node and
                instances[0]["State"]["Name"] == "terminated" and instances[0].get("VpcId", vpc) == vpc,
                f"Cannot verify terminated node {node} for ENI {identifier}")
        remove("delete-network-interface", "--network-interface-id", identifier, "InvalidNetworkInterfaceID.NotFound")
        g.until("ENI release " + identifier, lambda: not inventory(
            "describe-network-interfaces", "NetworkInterfaces", "Name=network-interface-id,Values=" + identifier))

    groups = inventory("describe-security-groups", "SecurityGroups")
    for group in groups:
        if group["GroupName"] == "default":
            continue
        sg = group["GroupId"]
        labels = tags(group.get("Tags", []))
        require(sg == journal.get("cluster_sg") and group["VpcId"] == vpc
                and group["GroupName"].startswith("eks-cluster-sg-" + g.context + "-")
                and labels.get("aws:eks:cluster-name") == g.context
                and labels.get("kubernetes.io/cluster/" + g.context) == "owned",
                "Review non-default security group in selected VPC: " + sg)
        attached = json.loads(g.aws("ec2", "describe-network-interfaces", "--filters", "Name=group-id,Values=" + sg))
        interfaces = [e["NetworkInterfaceId"] for e in attached["NetworkInterfaces"]]
        require(not interfaces, f"Cluster security group {sg} still attached to {interfaces}")
        references = [other["GroupId"] for other in groups if other["GroupId"] != sg and any(
            pair.get("GroupId") == sg for perm in other.get("IpPermissions", []) + other.get("IpPermissionsEgress", [])
            for pair in perm.get("UserIdGroupPairs", []))]
        require(not references, f"Cluster security group {sg} is referenced by {references}")
        remove("delete-security-group", "--group-id", sg, "InvalidGroup.NotFound")
