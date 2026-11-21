import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
from aws_dev_network import release_network
from configuration import OpsError


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.g = Mock(context="example-dev")
        self.g.until.side_effect = lambda description, read: self.assertTrue(read())
        self.eni = {"VpcId": "vpc", "NetworkInterfaceId": "eni-1", "SubnetId": "subnet-a", "InterfaceType": "interface",
                    "Status": "available", "RequesterManaged": False, "Description": "aws-K8S-i-ab", "Tags": [
                        {"Key": "eks:eni:owner", "Value": "amazon-vpc-cni"},
                        {"Key": "node.k8s.amazonaws.com/instance_id", "Value": "i-ab"},
                        {"Key": "cluster.k8s.amazonaws.com/name", "Value": "example-dev"}]}
        self.sg = {"GroupId": "sg-1", "GroupName": "eks-cluster-sg-example-dev-42", "VpcId": "vpc", "Tags": [
            {"Key": "aws:eks:cluster-name", "Value": "example-dev"},
            {"Key": "kubernetes.io/cluster/example-dev", "Value": "owned"}]}
        self.enis = [self.eni, {"NetworkInterfaceId": "eni-nat"}]
        self.groups = [self.sg, {"GroupId": "sg-default", "GroupName": "default"}]
        self.node_state = "terminated"
        self.clusters = []
        self.state = {"resources": [{"module": "module.vpc", "type": "aws_nat_gateway", "mode": "managed",
                                     "instances": [{"attributes": {"id": "nat-1"}}]}]}
        self.journal = {"cleaned": True, "vpc": "vpc", "cluster_sg": "sg-1"}
        self.mutations = []
        self.g.aws.side_effect = self.aws

    def aws(self, service, op, *args):
        if op.startswith("delete-"):
            self.mutations.append((op, args[-1]))
            if op == "delete-network-interface":
                self.enis.remove(self.eni)
            else:
                self.groups.remove(self.sg)
            return "{}"
        if op == "describe-network-interfaces":
            if any("Name=group-id" in a for a in args):
                return '{"NetworkInterfaces":[]}'
            enis = [e for e in self.enis if e is self.eni] if any("Name=network-interface-id" in a for a in args) else self.enis
            return json.dumps({"NetworkInterfaces": enis})
        if op == "describe-nat-gateways":
            self.assertEqual(args[0], "--filter")
        return json.dumps({"list-clusters": {"clusters": self.clusters},
                           "describe-nat-gateways": {"NatGateways": [{"NatGatewayAddresses": [{"NetworkInterfaceId": "eni-nat"}]}]},
                           "describe-instances": {"Reservations": [{"Instances": [
                               {"InstanceId": "i-ab", "State": {"Name": self.node_state}}]}]},
                           "describe-security-groups": {"SecurityGroups": self.groups}}[op])

    def test_order_nat_exclusion_and_retry(self):
        for _ in range(2):
            release_network(self.g, self.journal, self.state)
        self.assertEqual(self.mutations, [("delete-network-interface", "eni-1"), ("delete-security-group", "sg-1")])

    def test_live_cluster_or_node_blocks_and_unknown_sg_is_preserved(self):
        self.clusters = ["example-dev"]
        with self.assertRaisesRegex(OpsError, "absent"):
            release_network(self.g, self.journal, self.state)
        self.clusters = []
        self.node_state = "running"
        with self.assertRaisesRegex(OpsError, "eni-1"):
            release_network(self.g, self.journal, self.state)
        self.eni["RequesterManaged"] = True
        with self.assertRaisesRegex(OpsError, "eni-1"):
            release_network(self.g, self.journal, self.state)
        self.enis = []
        self.journal.pop("cluster_sg")
        with self.assertRaisesRegex(OpsError, "sg-1"):
            release_network(self.g, self.journal, self.state)
        self.assertFalse(self.mutations)
