#!/usr/bin/env python3
"""Validate the v0.12 quality-gate call graph without executing validators."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


ROOT_GATE = "validate-ci-quality-gates.sh"
STANDALONE = "validate-v0.12.1.0.1-ci-compatibility-repair.sh"
ORCHESTRATOR = "validate-v0.12.2.4.1-validator-orchestration-dedup.sh"
SUCCESSOR = "validate-v0.12.2.4.2-quality-gate-history-dedup.sh"
LATEST = "validate-v0.12.3.1-ci-change-impact-routing.sh"
REVIEWED_ROOT_SUCCESSORS = {
    "validate-v0.12.3.1.1-release-change-routing-repair.sh": LATEST,
}
ENTRYPOINT = "validate-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.sh"
EXPECTED_CHAIN_COUNT = 22

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
CALL_RE = re.compile(
    r"^\s*(?:bash\s+)?['\"]?\$\{ROOT_DIR\}/scripts/"
    r"(validate-v0\.12[0-9A-Za-z._-]*\.sh)['\"]?\s*$"
)


class TopologyError(ValueError):
    """Raised when validator orchestration is ambiguous or incomplete."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TopologyError(message)


def shell_lines_outside_heredocs(text: str) -> Iterable[str]:
    delimiter: str | None = None
    for line in text.splitlines():
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        yield line
        match = HEREDOC_RE.search(line)
        if match:
            delimiter = match.group(2)
    require(delimiter is None, "unterminated heredoc")


def extract_v012_calls(text: str) -> list[str]:
    calls: list[str] = []
    for line in shell_lines_outside_heredocs(text):
        match = CALL_RE.fullmatch(line)
        if match:
            calls.append(match.group(1))
    return calls


def walk_single_predecessor_chain(
    call_map: dict[str, list[str]], entrypoint: str
) -> list[str]:
    chain: list[str] = []
    current = entrypoint
    while True:
        require(current in call_map, f"missing validator: {current}")
        require(current not in chain, f"validator cycle: {current}")
        chain.append(current)
        predecessors = call_map[current]
        require(
            len(predecessors) <= 1,
            f"multiple v0.12 predecessors: {current}: {predecessors}",
        )
        if not predecessors:
            return chain
        current = predecessors[0]


def validate_repository(root: Path) -> dict[str, object]:
    scripts = root / "scripts"
    root_calls = extract_v012_calls((scripts / ROOT_GATE).read_text())
    if root_calls != [LATEST]:
        require(len(root_calls) == 1, f"root v0.12 calls changed: {root_calls}")
        successor = root_calls[0]
        require(
            REVIEWED_ROOT_SUCCESSORS.get(successor) == LATEST,
            f"unreviewed root v0.12 successor: {successor}",
        )
        # This historical parser also recognizes the successor's bash -n entry;
        # accept only that exact self marker followed by its real predecessor.
        successor_calls = extract_v012_calls((scripts / successor).read_text())
        require(
            successor_calls == [successor, LATEST],
            f"reviewed root successor delegation changed: {successor_calls}",
        )
        root_calls = [LATEST]

    latest_calls = extract_v012_calls((scripts / LATEST).read_text())
    require(
        latest_calls == [SUCCESSOR],
        f"latest v0.12 delegation changed: {latest_calls}",
    )

    successor_calls = extract_v012_calls((scripts / SUCCESSOR).read_text())
    require(
        successor_calls == [STANDALONE, ORCHESTRATOR],
        f"successor v0.12 delegation changed: {successor_calls}",
    )

    orchestrator_calls = extract_v012_calls((scripts / ORCHESTRATOR).read_text())
    require(
        orchestrator_calls == [ENTRYPOINT],
        f"orchestrator entrypoint changed: {orchestrator_calls}",
    )

    validators = sorted(path.name for path in scripts.glob("validate-v0.12*.sh"))
    expected_chain = set(validators) - {
        STANDALONE,
        ORCHESTRATOR,
        SUCCESSOR,
        LATEST,
        *REVIEWED_ROOT_SUCCESSORS,
    }
    require(STANDALONE in validators, "standalone compatibility validator missing")
    require(ORCHESTRATOR in validators, "orchestration validator missing")
    require(SUCCESSOR in validators, "successor orchestration validator missing")
    require(LATEST in validators, "latest orchestration validator missing")
    require(
        len(expected_chain) == EXPECTED_CHAIN_COUNT,
        f"unexpected chained validator inventory: {len(expected_chain)}",
    )

    call_map = {
        name: extract_v012_calls((scripts / name).read_text())
        for name in expected_chain
    }
    chain = walk_single_predecessor_chain(call_map, ENTRYPOINT)
    require(len(chain) == len(set(chain)), "duplicate validator in chain")
    require(
        set(chain) == expected_chain,
        "chained validator coverage changed: "
        f"missing={sorted(expected_chain - set(chain))}, "
        f"unexpected={sorted(set(chain) - expected_chain)}",
    )

    compatibility_branch_executions = 3
    old_effective_executions = compatibility_branch_executions + sum(
        range(1, len(chain) + 1)
    )
    new_effective_executions = compatibility_branch_executions + len(chain)

    return {
        "status": "v0.12-validator-orchestration-deduplicated",
        "root_direct_v0_12_validator_count": len(root_calls),
        "root_direct_v0_12_validators": root_calls,
        "latest_delegated_v0_12_validators": latest_calls,
        "successor_delegated_v0_12_validators": successor_calls,
        "unique_chained_validator_count": len(chain),
        "chained_entrypoint": ENTRYPOINT,
        "old_root_direct_v0_12_validator_count": 23,
        "v0_12_2_4_1_root_direct_v0_12_validator_count": 2,
        "successor_root_direct_v0_12_validator_count": 1,
        "v0_12_2_4_1_root_direct_invocation_reduction": 21,
        "old_effective_historical_validator_executions": old_effective_executions,
        "new_effective_historical_validator_executions": new_effective_executions,
        "duplicate_historical_validator_execution_reduction": (
            old_effective_executions - new_effective_executions
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    args = parser.parse_args()
    print(json.dumps(validate_repository(args.root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
