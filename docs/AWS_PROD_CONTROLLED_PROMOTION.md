# Controlled aws-test to aws-prod Promotion

v0.10.6 closes the GitOps release chain by allowing the orchestrator to prepare
one reviewed `aws-test -> aws-prod` release-only pull request. The action is
based on the merged, fresh aws-test Qualification Bundle and retains both
production human controls: protected GitHub Environment approval before the
job runs and CODEOWNERS/branch-protection review before the PR merges.

## Flow

```text
fresh aws-test Qualification Bundle on main
  -> derive prepare-prod-promotion
  -> DEMO_API_AWS_PROD_PROMOTION_ENABLED=true
  -> aws-prod GitHub Environment reviewer approval
  -> validate test Bundle, release identity, scope, expiry, and main SHA
  -> create aws-prod release-only PR
  -> CODEOWNERS and protected-branch review
  -> human merge
  -> complete / completed
```

`complete / completed` means that the immutable Release ID has reached the
aws-prod GitOps release file on protected `main`. It does not assert that an
aws-prod cluster exists or that production runtime qualification passed.

## Required GitHub Configuration

Create or retain the `aws-prod` GitHub Environment and configure required
reviewers. Repository Actions must be allowed to create pull requests, while
branch protection or a ruleset must require the checks and CODEOWNERS review
used by this repository.

Enable preparation only when a production PR is intended:

```text
DEMO_API_AWS_PROD_PROMOTION_ENABLED=true
```

When the variable is missing or not `true`, the orchestrator still derives the
next action but reports `automation-disabled` and does not enter the production
Environment or create a branch.

## Accepted Source Fact

The automated production path accepts only the Qualification Bundle reference
derived from the current protected-main snapshot. The Promotion stage verifies:

- the path is under the exact aws-test Release ID directory;
- the file and supplied SHA-256 match;
- the Bundle is qualified, unexpired, and valid against the current aws-test
  qualification Scope;
- the Bundle identity and release-file SHA-256 match the current aws-test
  release;
- protected `main` still equals the orchestrator control-plane SHA before the
  mutation and before PR creation.

The historical manual static/runtime evidence interface remains available for
operator compatibility. Automated orchestration uses Bundle mode and rejects
mixed inputs.

## Mutation and Permission Boundary

The approved job may change only:

```text
apps/demo-api/helm/values/releases/aws-prod.yaml
```

It may create a branch and pull request. It cannot:

- merge or auto-merge the PR;
- write directly to `main`;
- obtain AWS or EKS credentials;
- run `kubectl`, sync Argo CD, or promote/abort a Rollout;
- create an EKS cluster or apply Terraform;
- mutate Secrets, databases, or application runtime;
- invoke the production runtime executor;
- trigger rollback.

## Offline Validation

```bash
./scripts/validate-demo-api-aws-prod-orchestration.sh
./scripts/validate-demo-api-release-orchestrator.sh
./scripts/validate-reusable-delivery-stages.sh
./scripts/validate-release-orchestration-contract.sh
```

Live Workflow acceptance remains part of the later clean-room checkpoint.

v0.10.7 additionally requires at least 3600 seconds of source Bundle validity
when the Promotion stage executes. Long-lived production PRs must retain current
required checks and may require renewed test qualification before merge.
