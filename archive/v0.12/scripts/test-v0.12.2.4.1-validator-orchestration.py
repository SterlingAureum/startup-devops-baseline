#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("check-v0.12.2.4.1-validator-orchestration.py")
SPEC = importlib.util.spec_from_file_location("validator_orchestration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ParserTests(unittest.TestCase):
    def test_extracts_direct_shell_calls_and_ignores_heredoc_content(self) -> None:
        text = """#!/usr/bin/env bash
python3 - <<'PY'
fake = '${ROOT_DIR}/scripts/validate-v0.12.9-fake.sh'
PY
bash "${ROOT_DIR}/scripts/validate-v0.12.1-real.sh"
"${ROOT_DIR}/scripts/validate-v0.12.2-real.sh"
"""
        self.assertEqual(
            MODULE.extract_v012_calls(text),
            ["validate-v0.12.1-real.sh", "validate-v0.12.2-real.sh"],
        )

    def test_rejects_unterminated_heredoc(self) -> None:
        with self.assertRaisesRegex(MODULE.TopologyError, "unterminated heredoc"):
            MODULE.extract_v012_calls("python3 - <<'PY'\nmissing terminator\n")


class ChainTests(unittest.TestCase):
    def test_walks_one_predecessor_chain(self) -> None:
        call_map = {"c.sh": ["b.sh"], "b.sh": ["a.sh"], "a.sh": []}
        self.assertEqual(
            MODULE.walk_single_predecessor_chain(call_map, "c.sh"),
            ["c.sh", "b.sh", "a.sh"],
        )

    def test_rejects_cycle(self) -> None:
        with self.assertRaisesRegex(MODULE.TopologyError, "cycle"):
            MODULE.walk_single_predecessor_chain(
                {"a.sh": ["b.sh"], "b.sh": ["a.sh"]}, "a.sh"
            )

    def test_rejects_multiple_predecessors(self) -> None:
        with self.assertRaisesRegex(MODULE.TopologyError, "multiple"):
            MODULE.walk_single_predecessor_chain(
                {"a.sh": ["b.sh", "c.sh"], "b.sh": [], "c.sh": []}, "a.sh"
            )

    def test_rejects_missing_validator(self) -> None:
        with self.assertRaisesRegex(MODULE.TopologyError, "missing"):
            MODULE.walk_single_predecessor_chain({"a.sh": ["missing.sh"]}, "a.sh")


class RepositoryTopologyTests(unittest.TestCase):
    def test_repository_has_exact_deduplicated_topology(self) -> None:
        report = MODULE.validate_repository(SCRIPT.parents[1])
        self.assertEqual(report["root_direct_v0_12_validator_count"], 1)
        self.assertEqual(
            report["root_direct_v0_12_validators"],
            ["validate-v0.12.3.1-ci-change-impact-routing.sh"],
        )
        self.assertEqual(
            report["latest_delegated_v0_12_validators"],
            ["validate-v0.12.2.4.2-quality-gate-history-dedup.sh"],
        )
        self.assertEqual(report["successor_root_direct_v0_12_validator_count"], 1)
        self.assertEqual(report["unique_chained_validator_count"], 22)
        self.assertEqual(
            report["v0_12_2_4_1_root_direct_invocation_reduction"], 21
        )
        self.assertEqual(report["old_effective_historical_validator_executions"], 256)
        self.assertEqual(report["new_effective_historical_validator_executions"], 25)
        self.assertEqual(
            report["duplicate_historical_validator_execution_reduction"], 231
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
