# Promotion Governance, Evidence, and Rollback

## Purpose

v0.9.4-v0.9.5 place review, static evidence, and runtime evidence controls
around the ordered build-once chain:

```text
build -> aws-dev -> aws-test -> aws-prod
```

The workflows prepare Git changes only. They never merge pull requests, apply
Kubernetes resources, or receive EKS credentials.

Use `MULTI_ENVIRONMENT_RELEASE_RUNBOOK.md` as the canonical command-by-command
operator procedure. This document defines the governance rationale and
security boundary.

## Governance Flow

For `aws-dev -> aws-test` or `aws-test -> aws-prod`:

1. Confirm the source release on `main` is the release being qualified.
2. Dispatch `demo-api release qualification evidence` from `main` for the
   source environment.
3. Approve the source GitHub Environment job when required.
4. The workflow validates the isolated release schema, Helm lint/render, and
   exact digest availability in GHCR.
5. Review and merge its evidence-only PR.
6. Record the static evidence workflow run ID.
7. From a clean local `main` that can reach the restricted EKS endpoint, run
   `record-demo-api-runtime-evidence-aws.sh` for the source environment.
8. Review and merge the generated runtime-evidence-only PR and record its UTC
   evidence ID.
9. Dispatch `demo-api ordered environment promotion` from `main` with the
   source, target, static evidence run ID, and runtime evidence ID.
10. Approve the target GitHub Environment job when required.
11. Review and merge the CODEOWNERS-protected target-release-only PR.
12. Let the target Argo CD reconcile the merged desired state when that cluster
    exists.

The promotion fails closed if either record is absent from `main`, non-passing,
malformed, for another environment or ID, expired, or no longer matches the
source release SHA-256. Static evidence defaults to seven days; runtime
evidence defaults to three days. Promotion also rechecks the exact GHCR digest
and rejects a moving `main` before branch push and PR creation.

## Evidence Boundary

Evidence records use:

```text
evidence/demo-api/<source-environment>/<workflow-run-id>.json
```

The v0.9.4 schema records:

- source environment and release path;
- SHA-256 of the complete release file;
- image repository, tag, digest, and application version;
- source repository and commit;
- original build workflow run ID;
- evidence workflow run and attempt;
- qualified repository revision, actor, and UTC timestamp;
- the exact static qualification checks that passed.

This is static release qualification. It proves that the desired release is
well-formed, renders, and references an existing immutable artifact. It does
not prove live Pod readiness, ALB routing, AnalysisRun success, or cluster
health.

Runtime records use:

```text
evidence/demo-api/runtime/<source-environment>/<UTC-YYYYMMDDHHMMSS>.json
```

They prove the exact Argo CD Git revision, release annotations, ready Pod image
digest, HTTPS health/readiness/version identity and, for aws-test/aws-prod, a
Healthy Rollout, matching Successful AnalysisRun, and completed 100%-stable ALB
action. The collector runs locally so the GitHub-hosted governance jobs remain
outside the restricted EKS endpoint boundary. The generated JSON contains no
credentials, Pod IPs, Secret values, or kubeconfig data.

## Approval Boundary

Repository declarations are not sufficient by themselves. Configure GitHub:

- create Environments `aws-dev`, `aws-test`, and `aws-prod`;
- require designated reviewers for `aws-prod` and prevent self-review;
- protect `main` with pull requests and required code-owner review;
- keep `.github/CODEOWNERS` owned by a trusted repository administrator;
- allow Actions to create pull requests, but never to merge them;
- do not add AWS or Kubernetes secrets to these release-governance jobs.

The jobs set `deployment: false`: they still use Environment protection and
review rules but do not create a GitHub deployment object because they only
prepare Git evidence or release PRs. On GitHub Free, Pro, and Team, required
Environment reviewers are available only for public repositories; confirm the
repository plan/visibility before treating that external control as enforced.

The provided CODEOWNERS file assigns the current repository owner as the
initial reviewer. Teams should replace or extend that identity with their real
platform and production-approval groups.

## Environment Rollback

Dispatch `demo-api environment GitOps rollback` from `main` with:

```text
target_environment = aws-dev | aws-test | aws-prod
rollback_to_revision = <full historical commit SHA>
expected_current_release_id = <current target Release ID>
```

The selected commit must:

- be contained in current `main` history;
- have a parent commit;
- change exactly one file;
- change the selected environment's release file only;
- contain a complete, consistent immutable delivery identity;
- reference a source commit that remains available in repository history.

The workflow restores that file byte for byte, renders the selected Helm
profile, proves the old GHCR digest still exists, enters the target Environment,
rejects stale `main`, and creates a release-only rollback PR. Environment
configuration, Secrets, databases, Terraform state, and other environments are
never modified.

The required release-currentness check does not treat the intentionally older
rollback identity as a stale Promotion. It requires the generated PR metadata,
the exact rollback branch run ID/attempt, the selected historical commit, the
expected current Release, and the originating manual rollback workflow run to
agree. Naming an ordinary branch `rollback/*` is not sufficient to enter this
mode. The PR must pass both protected checks before it is eligible for a real
human-approved merge.

Rollback is a new forward Git commit after review. It does not rewrite history
and does not bypass Argo CD.

## Local Validation

```bash
./scripts/validate-demo-api-promotion.sh
./scripts/validate-demo-api-promotion-governance.sh
./scripts/validate-demo-api-aws-progressive-delivery.sh
./scripts/validate-demo-api-runtime-evidence-behavior.sh
./scripts/validate-ci-quality-gates.sh
```

The governance validator tests valid evidence, environment/run mismatch,
source-release drift, failed evidence, expiry, three-environment rollback
isolation, workflow permissions, manual-only triggers, no direct EKS access,
runtime evidence identity/freshness, ALB/AnalysisRun declarations, and
CODEOWNERS coverage.
