#!/usr/bin/env python3
"""Build and validate the append-only v0.10 final acceptance record."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


REPOSITORY = "SterlingAureum/startup-devops-baseline"
PROTECTED_REF = "refs/heads/main"
ENVIRONMENTS = ("aws-dev", "aws-test", "aws-prod")
RUNTIME_ENVIRONMENTS = ("aws-dev", "aws-test")
RUN_KEYS = {
    "statusReadOnly",
    "supersedeStatus",
    "environmentAbsent",
    "interrupted",
    "resumed",
    "devQualification",
    "testPromotion",
    "testQualification",
    "prodPromotion",
    "rollbackBoundary",
}
PR_KEYS = {
    "supersededRelease",
    "devQualification",
    "testPromotion",
    "testQualification",
    "prodPromotion",
    "rollbackBoundary",
}
RUNNER_PHASES = {"interrupted", "resumed"}
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
RELEASE_ID = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return parsed


def scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_release(path: Path) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    section: str | None = None
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
        elif indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            field = (section, key)
            require(field not in values, f"{path}:{number}: duplicate {section}.{key}")
            values[field] = scalar(value)
        else:
            raise ValueError(f"{path}:{number}: unsupported release values structure")
    required = {
        ("image", "repository"),
        ("image", "tag"),
        ("image", "digest"),
        ("release", "applicationVersion"),
        ("delivery", "sourceRepository"),
        ("delivery", "sourceCommit"),
        ("delivery", "workflowRunId"),
    }
    require(set(values) == required, f"{path}: isolated release fields changed")
    return values


def release_identity(root: Path) -> dict[str, Any]:
    documents: dict[str, dict[tuple[str, str], str]] = {}
    hashes: dict[str, str] = {}
    for environment in ENVIRONMENTS:
        path = root / f"apps/demo-api/helm/values/releases/{environment}.yaml"
        require(path.is_file(), f"Missing {environment} release file")
        documents[environment] = read_release(path)
        hashes[environment] = file_sha256(path)

    fields = (
        ("image", "repository"),
        ("image", "tag"),
        ("image", "digest"),
        ("release", "applicationVersion"),
        ("delivery", "sourceRepository"),
        ("delivery", "sourceCommit"),
        ("delivery", "workflowRunId"),
    )
    reference = documents["aws-prod"]
    for environment, values in documents.items():
        for field in fields:
            require(
                values[field] == reference[field],
                f"{environment} release identity differs at {'.'.join(field)}",
            )

    source = reference[("delivery", "sourceCommit")]
    digest = reference[("image", "digest")]
    repository = reference[("image", "repository")]
    source_repository = reference[("delivery", "sourceRepository")]
    require(SHA.fullmatch(source) is not None, "Invalid final source commit")
    require(DIGEST.fullmatch(digest) is not None, "Invalid final image digest")
    require(source_repository == REPOSITORY, "Unexpected final source repository")
    require(
        repository == "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
        "Unexpected final image repository",
    )
    release_id = f"demo-api-{source[:12]}-{digest.removeprefix('sha256:')[:12]}"
    return {
        "releaseId": release_id,
        "sourceCommit": source,
        "imageDigest": digest,
        "environmentReleaseSha256": hashes,
    }


def safe_repository_path(root: Path, raw: str) -> Path:
    require(bool(raw) and not raw.startswith("/"), "Evidence path must be relative")
    relative = Path(raw)
    require(".." not in relative.parts, "Evidence path must not traverse parents")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), "Evidence path escaped repository")
    require(path.is_file(), f"Referenced evidence file is missing: {raw}")
    return path


def acceptance_scope(root: Path, contract: dict[str, Any]) -> tuple[str, int]:
    patterns = contract.get("acceptanceScopePatterns")
    require(isinstance(patterns, list) and patterns, "Acceptance scope patterns missing")
    files: set[Path] = set()
    for pattern in patterns:
        require(isinstance(pattern, str) and pattern, "Invalid acceptance scope pattern")
        files.update(path for path in root.glob(pattern) if path.is_file())
    require(files, "Acceptance scope resolved no files")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def validate_structure(document: dict[str, Any]) -> None:
    top = {
        "schemaVersion",
        "version",
        "status",
        "recordedAt",
        "repository",
        "protectedRef",
        "validatedControlPlaneSha",
        "release",
        "qualificationBundles",
        "github",
        "recovery",
        "production",
        "cleanup",
        "verification",
    }
    require(set(document) == top, "Final evidence has missing or unknown fields")
    require(document["schemaVersion"] == "v0.10.8", "Unsupported evidence schema")
    require(document["version"] == "v0.10", "Unexpected version line")
    require(document["status"] == "accepted", "Final status must be accepted")
    utc(document["recordedAt"])
    require(document["repository"] == REPOSITORY, "Unexpected repository")
    require(document["protectedRef"] == PROTECTED_REF, "Unexpected protected ref")
    require(
        SHA.fullmatch(document["validatedControlPlaneSha"]) is not None,
        "Invalid validated control-plane SHA",
    )

    release = document["release"]
    require(
        set(release)
        == {"releaseId", "sourceCommit", "imageDigest", "environmentReleaseSha256"},
        "Invalid final Release structure",
    )
    require(RELEASE_ID.fullmatch(release["releaseId"]) is not None, "Invalid Release ID")
    require(SHA.fullmatch(release["sourceCommit"]) is not None, "Invalid source commit")
    require(DIGEST.fullmatch(release["imageDigest"]) is not None, "Invalid image digest")
    require(
        release["releaseId"]
        == f"demo-api-{release['sourceCommit'][:12]}-{release['imageDigest'].removeprefix('sha256:')[:12]}",
        "Release ID is not derived from source and digest",
    )
    release_hashes = release["environmentReleaseSha256"]
    require(set(release_hashes) == set(ENVIRONMENTS), "Release hash environments changed")
    require(all(SHA256.fullmatch(value) for value in release_hashes.values()), "Invalid release hash")

    bundles = document["qualificationBundles"]
    require(set(bundles) == set(RUNTIME_ENVIRONMENTS), "Bundle environments changed")
    for environment, reference in bundles.items():
        require(set(reference) == {"path", "sha256"}, f"Invalid {environment} Bundle reference")
        require(
            reference["path"].startswith(
                f"evidence/demo-api/qualification/{environment}/{release['releaseId']}/"
            )
            and reference["path"].endswith(".json"),
            f"Invalid {environment} Bundle path",
        )
        require(SHA256.fullmatch(reference["sha256"]) is not None, "Invalid Bundle hash")

    github = document["github"]
    require(set(github) == {"runs", "pullRequests", "runnerIsolation"}, "Invalid GitHub evidence")
    require(set(github["runs"]) == RUN_KEYS, "GitHub run set changed")
    require(
        all(RUN_ID.fullmatch(str(value)) for value in github["runs"].values()),
        "Invalid GitHub run ID",
    )
    require(set(github["pullRequests"]) == PR_KEYS, "GitHub PR set changed")
    require(
        all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in github["pullRequests"].values()),
        "Invalid GitHub pull-request number",
    )
    runner_isolation = github["runnerIsolation"]
    require(
        set(runner_isolation)
        == {"validator", "automaticUnregistrationVerified", "interrupted", "resumed"},
        "Invalid runtime runner-isolation evidence",
    )
    require(
        runner_isolation["validator"] == "scripts/validate-demo-api-runner-isolation.sh",
        "Unexpected runner-isolation validator",
    )
    require(
        runner_isolation["automaticUnregistrationVerified"] is True,
        "Ephemeral runner unregistration was not verified",
    )
    for phase in RUNNER_PHASES:
        fact = runner_isolation[phase]
        require(
            set(fact) == {"runId", "runAttempt", "runnerId", "runnerName"},
            f"Invalid {phase} runner fact",
        )
        require(fact["runId"] == github["runs"][phase], f"{phase} runner fact cites another run")
        require(
            isinstance(fact["runAttempt"], int)
            and not isinstance(fact["runAttempt"], bool)
            and fact["runAttempt"] > 0,
            f"Invalid {phase} run attempt",
        )
        require(
            isinstance(fact["runnerId"], int)
            and not isinstance(fact["runnerId"], bool)
            and fact["runnerId"] > 0,
            f"Invalid {phase} runner_id",
        )
        require(isinstance(fact["runnerName"], str) and fact["runnerName"], f"Invalid {phase} runner name")
    require(
        runner_isolation["interrupted"]["runnerId"]
        != runner_isolation["resumed"]["runnerId"],
        "Interrupted and resumed runs reused one registered runner_id",
    )

    recovery = document["recovery"]
    expected_recovery = {
        "statusReadOnlyNoDispatch": True,
        "environmentAbsentResumed": True,
        "interruptedRunRecovered": True,
        "duplicatePullRequestCreated": False,
        "supersededReleaseBlocked": True,
        "supersededPullRequestClosedByHuman": True,
        "expiryValidationMode": "deterministic-time-shift",
        "requalificationBehaviorValidated": True,
        "rollbackHandoffMode": "deterministic-handoff-plus-live-manual-pr",
        "rollbackAutomaticallyDispatched": False,
        "rollbackPullRequestMerged": False,
    }
    require(recovery == expected_recovery, "Recovery acceptance is incomplete or unsafe")

    production = document["production"]
    expected_production = {
        "mode": "prod-static",
        "environmentApprovalPassed": True,
        "releaseOnlyPullRequestMerged": True,
        "runtimeQualificationPerformed": False,
        "clusterCreated": False,
        "kubernetesWritesPerformed": False,
        "automaticMerge": False,
        "automaticRollback": False,
    }
    require(production == expected_production, "Production boundary was not preserved")

    cleanup = document["cleanup"]
    require(
        set(cleanup)
        == {"aws-dev", "aws-test", "ephemeralRunnersStopped", "activationVariablesDisabled"},
        "Invalid cleanup record",
    )
    require(cleanup["ephemeralRunnersStopped"] is True, "Ephemeral runners remain active")
    require(cleanup["activationVariablesDisabled"] is True, "Activation variables remain enabled")
    recorded_at = utc(document["recordedAt"])
    for environment in RUNTIME_ENVIRONMENTS:
        result = cleanup[environment]
        require(set(result) == {"status", "completedAt"}, f"Invalid {environment} cleanup")
        require(result["status"] == "residual-cost-audit-passed", f"{environment} cleanup failed")
        require(utc(result["completedAt"]) <= recorded_at, "Cleanup completed after evidence recording")

    verification = document["verification"]
    require(
        set(verification)
        == {
            "acceptanceContractSha256",
            "acceptanceScopeSha256",
            "acceptanceScopeFileCount",
            "offlineGate",
        },
        "Invalid verification record",
    )
    require(SHA256.fullmatch(verification["acceptanceContractSha256"]) is not None, "Invalid contract hash")
    require(SHA256.fullmatch(verification["acceptanceScopeSha256"]) is not None, "Invalid Scope hash")
    require(
        isinstance(verification["acceptanceScopeFileCount"], int)
        and verification["acceptanceScopeFileCount"] > 0,
        "Invalid Scope file count",
    )
    require(
        verification["offlineGate"] == "scripts/validate-v0.10-final-acceptance.sh",
        "Unexpected final offline gate",
    )


def verify_references(document: dict[str, Any], root: Path) -> None:
    validate_structure(document)
    contract_path = root / "delivery/contracts/v0.10-final-acceptance.json"
    require(contract_path.is_file(), "Final acceptance contract is missing")
    contract = json.loads(contract_path.read_text())
    expected_scope_hash, expected_scope_count = acceptance_scope(root, contract)
    verification = document["verification"]
    require(
        verification["acceptanceContractSha256"] == file_sha256(contract_path),
        "Final acceptance contract hash drifted",
    )
    require(
        verification["acceptanceScopeSha256"] == expected_scope_hash,
        "Final acceptance Scope drifted",
    )
    require(
        verification["acceptanceScopeFileCount"] == expected_scope_count,
        "Final acceptance Scope file count drifted",
    )
    require(document["release"] == release_identity(root), "Final release identity drifted")

    from demo_api_qualification_bundle import validate as validate_bundle

    for environment in RUNTIME_ENVIRONMENTS:
        reference = document["qualificationBundles"][environment]
        path = safe_repository_path(root, reference["path"])
        require(file_sha256(path) == reference["sha256"], f"{environment} Bundle hash drifted")
        bundle = json.loads(path.read_text())
        validate_bundle(bundle, root=root, require_fresh=False)
        require(bundle["environment"] == environment, "Bundle environment mismatch")
        require(bundle["status"] == "qualified", "Bundle is not qualified")
        require(bundle["releaseId"] == document["release"]["releaseId"], "Bundle Release mismatch")
        require(
            bundle["identity"]["sourceCommit"] == document["release"]["sourceCommit"]
            and bundle["identity"]["imageDigest"] == document["release"]["imageDigest"],
            "Bundle immutable identity mismatch",
        )
        orchestration = bundle["orchestration"]
        run_key = "devQualification" if environment == "aws-dev" else "testQualification"
        require(
            str(orchestration["workflowRunId"]) == document["github"]["runs"][run_key],
            f"{environment} Bundle does not belong to the recorded qualification run",
        )
        if environment == "aws-dev":
            require(
                document["github"]["runs"]["resumed"]
                == document["github"]["runs"]["devQualification"],
                "The resumed run must be the accepted aws-dev qualification run",
            )
            require(
                int(orchestration["workflowRunAttempt"])
                == document["github"]["runnerIsolation"]["resumed"]["runAttempt"],
                "aws-dev Bundle run attempt differs from runner-isolation evidence",
            )


def build_document(source: dict[str, Any], root: Path) -> dict[str, Any]:
    expected_source = {
        "schemaVersion",
        "recordedAt",
        "validatedControlPlaneSha",
        "qualificationBundles",
        "github",
        "recovery",
        "production",
        "cleanup",
    }
    require(set(source) == expected_source, "Input has missing or unknown fields")
    require(source["schemaVersion"] == "v0.10.8-input", "Unsupported input schema")
    utc(source["recordedAt"])
    require(SHA.fullmatch(source["validatedControlPlaneSha"]) is not None, "Invalid input main SHA")

    contract_path = root / "delivery/contracts/v0.10-final-acceptance.json"
    contract = json.loads(contract_path.read_text())
    scope_hash, scope_count = acceptance_scope(root, contract)
    release = release_identity(root)
    bundle_references: dict[str, dict[str, str]] = {}
    require(set(source["qualificationBundles"]) == set(RUNTIME_ENVIRONMENTS), "Input Bundle environments changed")
    for environment in RUNTIME_ENVIRONMENTS:
        raw = source["qualificationBundles"][environment]
        path = safe_repository_path(root, raw)
        bundle_references[environment] = {"path": raw, "sha256": file_sha256(path)}

    document = {
        "schemaVersion": "v0.10.8",
        "version": "v0.10",
        "status": "accepted",
        "recordedAt": source["recordedAt"],
        "repository": REPOSITORY,
        "protectedRef": PROTECTED_REF,
        "validatedControlPlaneSha": source["validatedControlPlaneSha"],
        "release": release,
        "qualificationBundles": bundle_references,
        "github": source["github"],
        "recovery": source["recovery"],
        "production": source["production"],
        "cleanup": source["cleanup"],
        "verification": {
            "acceptanceContractSha256": file_sha256(contract_path),
            "acceptanceScopeSha256": scope_hash,
            "acceptanceScopeFileCount": scope_count,
            "offlineGate": "scripts/validate-v0.10-final-acceptance.sh",
        },
    }
    verify_references(document, root)
    return document
