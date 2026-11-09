#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-reviewed-aws-dev-qualification-for-promotion.py"
EVIDENCE = ROOT / "delivery/contracts/v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.json"
RELEASE = ROOT / "apps/demo-api/helm/values/releases/aws-dev.yaml"
RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReviewedLivePromotionTests(unittest.TestCase):
    def invoke(
        self,
        evidence: Path,
        release: Path,
        *,
        evidence_sha: str | None = None,
        release_sha: str | None = None,
        release_id: str = RELEASE_ID,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(VALIDATOR),
                "--evidence-contract",
                str(evidence),
                "--release-file",
                str(release),
                "--expected-contract-sha256",
                evidence_sha or digest(evidence),
                "--expected-release-sha256",
                release_sha or digest(release),
                "--expected-release-id",
                release_id,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_reviewed_contract_and_release_are_accepted(self) -> None:
        result = self.invoke(EVIDENCE, RELEASE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release-only promotion", result.stdout)

    def test_contract_byte_change_is_rejected(self) -> None:
        result = self.invoke(EVIDENCE, RELEASE, evidence_sha="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contract SHA-256 changed", result.stderr)

    def test_semantically_failed_execution_is_rejected_even_with_matching_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            value = json.loads(EVIDENCE.read_text())
            value["execution"]["runtimeQualified"] = False
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            result = self.invoke(path, RELEASE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtimeQualified", result.stderr)

    def test_wrong_release_id_is_rejected(self) -> None:
        result = self.invoke(EVIDENCE, RELEASE, release_id="demo-api-000000000000-000000000000")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release ID", result.stderr)

    def test_release_byte_change_is_rejected(self) -> None:
        result = self.invoke(EVIDENCE, RELEASE, release_sha="f" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release SHA-256 changed", result.stderr)

    def test_semantically_changed_release_is_rejected_even_with_matching_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aws-dev.yaml"
            path.write_text(RELEASE.read_text().replace('tag: "sha-cf0a6bc"', 'tag: "sha-0000000"'))
            result = self.invoke(EVIDENCE, path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source tag differs", result.stderr)


if __name__ == "__main__":
    unittest.main()
