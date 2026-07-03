# GitOps Workflow

This document describes the intended GitOps workflow for the repository.

The current implementation uses Argo CD and a root application.

## Current Flow

```text
Git repository
  -> Argo CD root application
  -> clusters/local/platform
  -> future platform and application Argo CD apps
```

The root application manifest is:

```text
clusters/local/root-app.yaml
```

The current root application points to:

```text
clusters/local/platform
```

That directory will later contain child Argo CD applications for ingress, monitoring, and the demo API.

## Repository URL

For Argo CD to sync correctly, the repository must be reachable from the cluster.

After pushing the repository to GitHub, deploy the root app with:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

## Current Status

The current batch prepares the GitOps entrypoint only.

Real workload sync will be added in later batches.
