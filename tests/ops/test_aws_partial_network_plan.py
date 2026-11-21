"""Offline Terraform regression for an interrupted, two-AZ dev destroy."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("terraform"), "requires Terraform CLI")
class PartialNetworkTests(unittest.TestCase):
    def test_checked_service_then_single_subnet_destroy(self):
        production = (Path(__file__).resolve().parents[2] / "infra/terraform/aws/modules/vpc/outputs.tf").read_text()
        # Exercise the actual for_each output expressions with Terraform's built-in provider.
        start = production.index('output "private_subnet_ids"')
        end = production.index('output "public_route_table_id"', start)
        output = production[start:end].replace("aws_subnet.private", "terraform_data.private")
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "main.tf").write_text('''
variable "availability_zones" { default = ["az-b", "az-a"] }
resource "terraform_data" "private" { for_each = toset(var.availability_zones) }
resource "terraform_data" "eks" { input = [for s in terraform_data.private : s.id] }
resource "terraform_data" "retained" {}
''' + output)
            def tf(*args):
                return subprocess.run(["terraform", *args], cwd=folder, capture_output=True, text=True, check=True).stdout
            tf("init", "-input=false")
            tf("apply", "-input=false", "-auto-approve")
            before = json.loads(tf("output", "-json", "private_subnet_ids"))
            survivor = tf("state", "show", "-no-color", 'terraform_data.private["az-b"]')
            self.assertIn(before[0], survivor)
            tf("plan", "-destroy", "-target=terraform_data.eks", "-out=service.tfplan")
            tf("apply", "service.tfplan")
            tf("state", "rm", 'terraform_data.private["az-a"]')
            tf("plan", "-destroy", '-target=terraform_data.private["az-b"]', "-out=network.tfplan")
            plan = json.loads(tf("show", "-json", "network.tfplan"))
            self.assertEqual([(c["address"], c["change"]["actions"]) for c in plan["resource_changes"]],
                             [('terraform_data.private["az-b"]', ["delete"])])
            tf("apply", "network.tfplan")
            self.assertEqual(tf("state", "list").strip(), "terraform_data.retained")
