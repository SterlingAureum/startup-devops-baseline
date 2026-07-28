# GitOps Image Rollback

## Purpose

v0.7.4 restores a previously reviewed demo-api release without allowing CI to
deploy directly to Kubernetes.

```text
operator selects historical desired-state commit
  -> GitHub Actions validates its release identity
  -> rollback branch restores values-aws-dev.yaml
  -> human reviews and merges the values-only pull request
  -> Argo CD reconciles the approved Git revision
  -> delivery trace verifies the restored runtime identity
```

The workflow never uses AWS credentials, `kubectl`, kubeconfig, or the Argo CD
API. It prepares Git desired state only.

## Eligible Rollback Target

`rollback_to_revision` must be the full 40-character commit SHA of a historical
desired-state commit contained in the selected base branch. Relative to its
first parent, that commit must change only:

```text
apps/demo-api/helm/values-aws-dev.yaml
```

The historical file must contain a complete v0.7.3-or-later delivery identity:

```text
image.repository
image.tag = sha-<first-seven-source-commit-characters>
image.digest = sha256:<64-lowercase-hex-characters>
env.APP_VERSION = image.tag
delivery.sourceRepository
delivery.sourceCommit = <full-commit>
delivery.workflowRunId
```

The source commit must also exist in repository history. A generic application
commit, a pre-metadata promotion, a commit outside the selected branch, or a
commit changing multiple files is rejected.

## Find a Target

Start from the branch that will receive the rollback:

```bash
git switch main
git pull --ff-only
git log --first-parent --oneline -- \
  apps/demo-api/helm/values-aws-dev.yaml
```

Inspect a candidate before dispatching:

```bash
git show --stat <candidate-commit>
git show <candidate-commit>:apps/demo-api/helm/values-aws-dev.yaml
```

Choose an older commit with non-empty `image.digest` and `delivery` fields.
Copy its full SHA:

```bash
git rev-parse <candidate-commit>
```

## Create the Rollback PR

In GitHub:

1. Open **Actions**.
2. Select **demo-api GitOps rollback**.
3. Choose **Run workflow**.
4. Select the branch containing the v0.7.4 workflow.
5. Enter the full SHA in `rollback_to_revision`.
6. Set `rollback_base_branch` to the branch that should receive the PR.
7. Run the workflow.

For feature-branch validation, both the workflow branch and
`rollback_base_branch` should be:

```text
feature/v0.7-cicd-gitops-promotion
```

For the final live exercise, both should be `main`.

The generated branch is deterministic for the selected target and base head.
Rerunning the same request reuses the branch and open PR. If the selected
historical values are already current, the workflow reports
`already-restored` and does not create an empty PR.

## Review Boundary

Before merge, confirm:

```bash
gh pr diff <rollback-pr-number> --name-only
```

Expected output:

```text
apps/demo-api/helm/values-aws-dev.yaml
```

Then review the restored tag, digest, source commit, and workflow run ID. The
workflow cannot approve or merge its own PR. Repository branch protection and
the human review decision remain authoritative.

## Verify the Live Rollback

After merging the rollback PR, wait until Argo CD reports the `demo-api-aws-dev`
Application as `Synced` and `Healthy`. Pull the exact merged branch and resolve
the commit that Argo CD reports:

```bash
git switch main
git pull --ff-only
ROLLBACK_DESIRED_REVISION="$(git rev-parse HEAD)"
```

If additional commits reached `main`, use the exact rollback merge or squash
commit shown by Argo CD instead of `HEAD`.

Run:

```bash
DESIRED_REVISION="${ROLLBACK_DESIRED_REVISION}" \
./scripts/validate-demo-api-delivery-trace.sh
```

The validator requires the Argo CD revision to equal the selected commit. It
then checks that Git, Deployment annotations, digest-pinned container image,
every Pod `imageID`, and every `/version` response all identify the historical
release.

## Recovery From a Rejected Target

The workflow fails closed and does not push a branch when the target is
ineligible. Select a metadata-aware values-only release commit from the same
base branch and rerun. Do not weaken the target checks and do not manually
substitute a mutable tag for the historical digest.

If the rollback PR is correct but the live trace fails, keep Git as the source
of truth:

1. confirm the PR was merged into the branch tracked by Argo CD;
2. confirm Argo CD is synced to the exact merge or squash commit;
3. wait for the Deployment rollout to finish;
4. rerun the trace with that exact commit as `DESIRED_REVISION`.
