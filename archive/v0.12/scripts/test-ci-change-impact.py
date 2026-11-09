#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("classify-ci-change-impact.py")
SPEC = importlib.util.spec_from_file_location("change_impact", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Repository:
    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"], check=True)
        return self

    def __exit__(self, *args):
        self.temporary.cleanup()

    def commit(self, path: str, content: str) -> str:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", path], check=True)
        return subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
        ).strip()


class ClassificationTests(unittest.TestCase):
    def test_documentation_only_change_is_fast(self):
        with Repository() as repository:
            base = repository.commit("README.md", "one\n")
            head = repository.commit("docs/guide.md", "two\n")
            report = MODULE.classify(repository.root, "auto", "push", base, head)
            self.assertEqual(report["mode"], "documentation")
            self.assertEqual(report["changedPathCount"], 1)

    def test_script_change_is_full(self):
        with Repository() as repository:
            base = repository.commit("README.md", "one\n")
            head = repository.commit("scripts/example.sh", "#!/bin/sh\n")
            report = MODULE.classify(repository.root, "auto", "push", base, head)
            self.assertEqual(report["mode"], "full")

    def test_exact_release_change_is_targeted_for_pull_request_and_push(self):
        for environment in ("aws-dev", "aws-test", "aws-prod"):
            for event in ("pull_request", "push"):
                with self.subTest(environment=environment, event=event):
                    with Repository() as repository:
                        path = f"apps/demo-api/helm/values/releases/{environment}.yaml"
                        base = repository.commit(path, "image: old\n")
                        head = repository.commit(path, "image: new\n")
                        report = MODULE.classify(
                            repository.root, "auto", event, base, head
                        )
                        self.assertEqual(report["mode"], "release")
                        self.assertEqual(
                            report["reason"], "exact-demo-api-release-change"
                        )
                        self.assertTrue(report["releaseOnly"])

    def test_release_change_mixed_with_any_other_path_is_full(self):
        with Repository() as repository:
            release = "apps/demo-api/helm/values/releases/aws-dev.yaml"
            base = repository.commit(release, "image: old\n")
            (repository.root / release).write_text("image: new\n")
            script = repository.root / "scripts/example.sh"
            script.parent.mkdir(parents=True)
            script.write_text("#!/bin/sh\n")
            subprocess.run(
                ["git", "-C", str(repository.root), "add", "-A"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repository.root), "commit", "-q", "-m", "mixed"],
                check=True,
            )
            head = subprocess.check_output(
                ["git", "-C", str(repository.root), "rev-parse", "HEAD"], text=True
            ).strip()
            report = MODULE.classify(repository.root, "auto", "push", base, head)
            self.assertEqual(report["mode"], "full")
            self.assertFalse(report["releaseOnly"])

    def test_release_adjacent_paths_are_full(self):
        for path in (
            "apps/demo-api/helm/values/releases/aws-stage.yaml",
            "apps/demo-api/helm/values/environments/aws-dev.yaml",
            "apps/demo-api/helm/values/releases/aws-dev.yaml.bak",
        ):
            with self.subTest(path=path):
                with Repository() as repository:
                    base = repository.commit("README.md", "one\n")
                    head = repository.commit(path, "value\n")
                    report = MODULE.classify(
                        repository.root, "auto", "push", base, head
                    )
                    self.assertEqual(report["mode"], "full")

    def test_validator_bound_documentation_is_full(self):
        with Repository() as repository:
            repository.commit("docs/guide.md", "one\n")
            base = repository.commit(
                "scripts/validate-guide.sh",
                '#!/bin/sh\ngrep -F "docs/guide.md" README.md\n',
            )
            head = repository.commit("docs/guide.md", "two\n")
            report = MODULE.classify(repository.root, "auto", "push", base, head)
            self.assertEqual(report["mode"], "full")
            self.assertEqual(report["reason"], "validator-bound-documentation")

    def test_rename_from_core_to_docs_is_full(self):
        with Repository() as repository:
            base = repository.commit("scripts/example.sh", "#!/bin/sh\n")
            (repository.root / "docs").mkdir()
            (repository.root / "scripts/example.sh").rename(repository.root / "docs/example.md")
            subprocess.run(["git", "-C", str(repository.root), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repository.root), "commit", "-q", "-m", "rename"], check=True)
            head = subprocess.check_output(
                ["git", "-C", str(repository.root), "rev-parse", "HEAD"], text=True
            ).strip()
            report = MODULE.classify(repository.root, "auto", "push", base, head)
            self.assertEqual(report["mode"], "full")

    def test_unknown_and_ambiguous_inputs_fail_closed(self):
        with Repository() as repository:
            head = repository.commit("README.md", "one\n")
            for requested, event, base in (
                ("unexpected", "push", head),
                ("auto", "workflow_dispatch", head),
                ("auto", "push", "0" * 40),
                ("auto", "push", "f" * 40),
            ):
                with self.subTest(requested=requested, event=event, base=base):
                    report = MODULE.classify(repository.root, requested, event, base, head)
                    self.assertEqual(report["mode"], "full")

    def test_explicit_modes_do_not_need_a_diff(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(MODULE.classify(root, "full", "", "", "")["mode"], "full")
        self.assertEqual(MODULE.classify(root, "image", "", "", "")["mode"], "image")

    def test_explicit_release_request_is_not_exposed(self):
        root = Path(tempfile.mkdtemp())
        report = MODULE.classify(root, "release", "", "", "")
        self.assertEqual(report["mode"], "full")
        self.assertEqual(report["reason"], "unknown-requested-mode")


if __name__ == "__main__":
    unittest.main(verbosity=2)
