#!/usr/bin/env python3
"""Fail-closed validation for deduplicated historical quality-gate execution."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Iterable


ROOT_GATE = "validate-ci-quality-gates.sh"
LATEST_ORCHESTRATOR = "validate-v0.12.3.1-ci-change-impact-routing.sh"
PREDECESSOR_ORCHESTRATOR = "validate-v0.12.3.1.1-release-change-routing-repair.sh"
REVIEWED_ROOT_SUCCESSORS = {
    PREDECESSOR_ORCHESTRATOR: LATEST_ORCHESTRATOR,
    "validate-v0.12.3.2-post-promotion-historical-snapshot.sh": PREDECESSOR_ORCHESTRATOR,
}
GLOBAL_ORCHESTRATOR = "validate-v0.12.2.4.2-quality-gate-history-dedup.sh"
V012_ORCHESTRATOR = "validate-v0.12.2.4.1-validator-orchestration-dedup.sh"
V012_COMPATIBILITY = "validate-v0.12.1.0.1-ci-compatibility-repair.sh"
MANIFEST = "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
EXPECTED_V011_INVENTORY = 168
EXPECTED_V011_ENTRYPOINTS = 112

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
CALL_RE = re.compile(
    r"^\s*(?:bash\s+)?['\"]?\$\{?ROOT_DIR\}?/scripts/"
    r"(validate-[0-9A-Za-z._-]+\.sh)['\"]?(?:\s+.*)?$"
)
RAW_V011_RE = re.compile(
    r"\$\{ROOT_DIR\}/scripts/(validate-v0\.11[0-9A-Za-z._-]*\.sh)"
)


class TopologyError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TopologyError(message)


def shell_logical_lines(text: str) -> Iterable[str]:
    delimiter: str | None = None
    pending = ""
    for raw in text.splitlines():
        if delimiter is not None:
            if raw.strip() == delimiter:
                delimiter = None
            continue
        line = pending + raw.lstrip() if pending else raw
        heredoc = HEREDOC_RE.search(line)
        if heredoc:
            delimiter = heredoc.group(2)
            pending = ""
            continue
        if line.rstrip().endswith("\\"):
            pending = line.rstrip()[:-1] + " "
            continue
        yield line
        pending = ""
    require(delimiter is None, "unterminated heredoc")
    require(not pending, "unterminated shell continuation")


def extract_validator_calls(text: str) -> list[str]:
    calls: list[str] = []
    for line in shell_logical_lines(text):
        match = CALL_RE.fullmatch(line)
        if match:
            calls.append(match.group(1))
    return calls


def reachable(graph: dict[str, list[str]], start: str) -> set[str]:
    result: set[str] = set()
    active: list[str] = []

    def visit(name: str) -> None:
        require(name not in active, f"validator cycle: {' -> '.join(active + [name])}")
        if name in result:
            return
        require(name in graph, f"missing validator: {name}")
        active.append(name)
        result.add(name)
        for child in graph[name]:
            visit(child)
        active.pop()

    visit(start)
    return result


def expansion_counts(
    graph: dict[str, list[str]], roots: list[str]
) -> Counter[str]:
    memo: dict[str, Counter[str]] = {}
    active: list[str] = []

    def expand(name: str) -> Counter[str]:
        require(name in graph, f"missing validator: {name}")
        if name in memo:
            return memo[name].copy()
        require(name not in active, f"validator cycle: {' -> '.join(active + [name])}")
        active.append(name)
        result: Counter[str] = Counter({name: 1})
        for child in graph[name]:
            result.update(expand(child))
        active.pop()
        memo[name] = result.copy()
        return result

    total: Counter[str] = Counter()
    for root in roots:
        total.update(expand(root))
    return total


def read_manifest(root: Path) -> list[str]:
    lines = (root / MANIFEST).read_text().splitlines()
    require(lines and all(line and line == line.strip() for line in lines), "invalid manifest line")
    require(len(lines) == len(set(lines)), "duplicate manifest entry")
    return lines


def validate_repository(root: Path) -> dict[str, object]:
    scripts = root / "scripts"
    files = {path.name: path for path in scripts.glob("validate-*.sh")}
    graph = {
        name: extract_validator_calls(path.read_text())
        for name, path in files.items()
    }
    manifest = read_manifest(root)
    require(len(manifest) == EXPECTED_V011_ENTRYPOINTS, "v0.11 entrypoint count drift")
    require(all(name in files for name in manifest), "manifest validator missing")

    literal_global_calls = graph[GLOBAL_ORCHESTRATOR]
    require(
        literal_global_calls == [V012_COMPATIBILITY, V012_ORCHESTRATOR],
        f"global v0.12 delegation drift: {literal_global_calls}",
    )
    graph[GLOBAL_ORCHESTRATOR] = [V012_COMPATIBILITY, *manifest, V012_ORCHESTRATOR]
    literal_latest_calls = graph[LATEST_ORCHESTRATOR]
    require(
        literal_latest_calls == [GLOBAL_ORCHESTRATOR, GLOBAL_ORCHESTRATOR],
        f"latest conditional orchestration drift: {literal_latest_calls}",
    )
    graph[LATEST_ORCHESTRATOR] = [GLOBAL_ORCHESTRATOR]

    v011 = {name for name in files if name.startswith("validate-v0.11")}
    require(len(v011) == EXPECTED_V011_INVENTORY, "v0.11 validator inventory drift")
    called_by_v011 = {
        child
        for name in v011
        for child in graph[name]
        if child in v011
    }
    maximal = v011 - called_by_v011
    precovered = (
        reachable(graph, V012_COMPATIBILITY)
        | reachable(graph, V012_ORCHESTRATOR)
    ) & v011
    expected_entrypoints = maximal - precovered

    root_text = (scripts / ROOT_GATE).read_text()
    legacy_order: list[str] = []
    for match in RAW_V011_RE.finditer(root_text):
        name = match.group(1)
        if name not in legacy_order:
            legacy_order.append(name)
    expected_order = [name for name in legacy_order if name in expected_entrypoints]
    require(set(legacy_order) == v011, "legacy v0.11 registration coverage drift")
    require(manifest == expected_order, "v0.11 entrypoint manifest drift")

    root_calls = extract_validator_calls(root_text)
    require(not any(name.startswith("validate-v0.11") for name in root_calls), "root directly executes v0.11")
    root_v012_calls = [name for name in root_calls if name.startswith("validate-v0.12")]
    while root_v012_calls != [LATEST_ORCHESTRATOR]:
        require(len(root_v012_calls) == 1, "root v0.12 orchestration drift")
        successor = root_v012_calls[0]
        predecessor = REVIEWED_ROOT_SUCCESSORS.get(successor)
        require(
            predecessor is not None,
            "unreviewed root v0.12 successor",
        )
        require(
            graph.get(successor) == [predecessor, predecessor],
            "reviewed root successor conditional delegation drift",
        )
        graph[successor] = [predecessor]
        root_calls = [
            predecessor if name == successor else name for name in root_calls
        ]
        root_v012_calls = [
            name for name in root_calls if name.startswith("validate-v0.12")
        ]

    counts = expansion_counts(graph, root_calls)
    reachable_v011 = {name for name in counts if name in v011}
    require(reachable_v011 == v011, "v0.11 coverage incomplete")
    effective_v011 = sum(counts[name] for name in v011)
    historical_v012 = {
        name
        for name in files
        if name.startswith("validate-v0.12")
        and name not in {V012_ORCHESTRATOR, GLOBAL_ORCHESTRATOR, LATEST_ORCHESTRATOR}
    }
    effective_historical_v012 = sum(counts[name] for name in historical_v012)
    effective_v012_orchestration = (
        counts[V012_ORCHESTRATOR]
        + counts[GLOBAL_ORCHESTRATOR]
        + counts[LATEST_ORCHESTRATOR]
    )

    require(len(root_calls) == 29, f"root direct validator count drift: {len(root_calls)}")
    require(effective_v011 == 176, f"v0.11 effective count drift: {effective_v011}")
    require(effective_historical_v012 == 25, "historical v0.12 effective count drift")
    require(effective_v012_orchestration == 3, "v0.12 orchestration count drift")
    require(sum(counts.values()) == 246, f"effective validator count drift: {sum(counts.values())}")

    return {
        "status": "quality-gate-history-orchestration-deduplicated",
        "root_direct_validator_count": len(root_calls),
        "root_direct_v0_11_validator_count": 0,
        "delegated_v0_11_entrypoint_count": len(manifest),
        "unique_reachable_v0_11_validator_count": len(reachable_v011),
        "effective_v0_11_validator_execution_count": effective_v011,
        "effective_historical_v0_12_validator_execution_count": effective_historical_v012,
        "effective_v0_12_orchestration_execution_count": effective_v012_orchestration,
        "effective_validator_execution_count": sum(counts.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(validate_repository(args.root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
