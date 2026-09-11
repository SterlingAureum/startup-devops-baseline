#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/preflight-v0.11.9.3.6.6.5-aws-dev-teardown.py"
spec = importlib.util.spec_from_file_location("teardown_preflight", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = "f" * 40


def runner(arguments: list[str]) -> str:
    key = " ".join(arguments)
    if key == "git branch --show-current": return "main"
    if key == "git status --porcelain": return ""
    if key in ("git rev-parse HEAD", "git rev-parse origin/main"): return SHA
    if key == "aws sts get-caller-identity --output json": return json.dumps({"Account": "123456789012"})
    if "eks list-clusters" in key: return json.dumps({"clusters": [module.DEV_CLUSTER]})
    if "eks describe-cluster" in key: return json.dumps({"cluster": {"name": module.DEV_CLUSTER, "status": "ACTIVE", "version": "1.36"}})
    if f"-chdir={module.TF_DEV} state list" in key: return "module.eks.aws_eks_cluster.this\nmodule.vpc.aws_vpc.this"
    if f"-chdir={module.TF_TEST} state list" in key: return ""
    if key.endswith("output -raw cluster_name"): return module.DEV_CLUSTER
    if key.endswith("output -raw vpc_id"): return "vpc-1234abcd"
    if key.endswith("output -raw cnpg_backup_bucket_name"): return "private-bucket"
    if key == "aws s3api head-bucket --bucket private-bucket": return ""
    raise AssertionError(key)


class Tests(unittest.TestCase):
    def env(self):
        return mock.patch.dict(os.environ, {
            "CONFIRM_AWS_DEV_TEARDOWN_PREFLIGHT": module.CONFIRMATION,
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
        }, clear=True)

    @mock.patch.object(module.shutil, "which", return_value="/bin/tool")
    def test_ready_result_is_redacted_and_non_authorizing(self, _which):
        with self.env(): result = module.execute(SHA, runner)
        self.assertEqual(result["status"], "aws-dev-teardown-preflight-ready-for-separate-approval")
        self.assertFalse(result["teardown_authorized"])
        self.assertFalse(result["mutation_executed"])
        self.assertNotIn("123456789012", json.dumps(result))
        self.assertNotIn("private-bucket", json.dumps(result))

    @mock.patch.object(module.shutil, "which", return_value="/bin/tool")
    def test_destructive_confirmation_is_rejected(self, _which):
        with self.env(), mock.patch.dict(os.environ, {"CONFIRM_AWS_ENVIRONMENT_DESTROY": "destroy-with-backups"}):
            with self.assertRaisesRegex(ValueError, "Destructive"): module.execute(SHA, runner)

    @mock.patch.object(module.shutil, "which", return_value="/bin/tool")
    def test_other_cluster_blocks(self, _which):
        def changed(arguments):
            if "eks" in arguments and "list-clusters" in arguments:
                return json.dumps({"clusters": [module.DEV_CLUSTER, module.TEST_CLUSTER]})
            return runner(arguments)
        with self.env():
            with self.assertRaisesRegex(ValueError, "only active"): module.execute(SHA, changed)


if __name__ == "__main__": unittest.main()
