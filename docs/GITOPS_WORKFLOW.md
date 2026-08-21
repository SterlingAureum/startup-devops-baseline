# GitOps Workflow

This repository uses Argo CD to implement a local GitOps workflow.

## Core Idea

Git is the source of truth. Argo CD watches the repository and reconciles the Kubernetes cluster to match the desired state stored in Git.

## Application Structure

The v0.1 baseline uses an app-of-apps pattern:

```text
startup-devops-root
  |
  +-- ingress-nginx
  +-- demo-api
  +-- monitoring
```

## Root Application

The root application is defined at:

```text
clusters/local/root-app.yaml
```

It points Argo CD to:

```text
clusters/local/platform/
```

That directory is a lightweight Helm App-of-Apps Chart. Its templates render
the child Argo CD Applications.

## Child Applications

Child applications include:

```text
clusters/local/platform/templates/demo-api.yaml
clusters/local/platform/templates/ingress-nginx.yaml
clusters/local/platform/templates/monitoring.yaml
```

Each child Application points to its own source path or Helm chart.

## demo-api Application

The demo-api Application points to:

```text
apps/demo-api/helm
```

Argo CD renders the Helm chart and deploys the workload into:

```text
startup-apps
```

## ingress-nginx Application

The ingress-nginx Application installs the ingress controller into:

```text
ingress-nginx
```

It allows the demo-api service to be reached through local HTTP ingress.

## monitoring Application

The monitoring Application deploys a lightweight Prometheus stack into:

```text
monitoring
```

Prometheus is configured to scrape the demo-api `/metrics` endpoint.

## Standard Deployment Flow

1. Update code, Helm values, or manifests.
2. Commit changes.
3. Push to GitHub.
4. Argo CD detects the change.
5. Argo CD syncs the target Application.
6. Run `scripts/validate.sh`.

## Manual Refresh

Argo CD polls Git periodically. For local testing, you can force a refresh:

```bash
kubectl -n argocd annotate application startup-devops-root \
  argocd.argoproj.io/refresh=hard --overwrite
```

This does not manually deploy the workload. It tells Argo CD to refresh its view of Git immediately.

## Manual Apply as a Fallback

In normal workflow, only the root application should be manually created.

Avoid manually applying child applications unless you are debugging the root app.

Recommended:

```bash
REPO_URL=https://github.com/<your-user>/startup-devops-baseline.git \
  ./scripts/deploy-root-app.sh
```

For a local feature-revision acceptance run, use the unified Root-rendered
workflow instead of applying a child template manually:

```bash
TARGET_REVISION=feature/v0.11-observability-sre-baseline \
IMAGE_TAG=v0.11.3-local \
  ./scripts/deploy-local-feature-gitops.sh
```

The workflow resolves the branch to one immutable commit and renders that same
commit into Root, namespace guardrails, and demo-api. Root remains manual but
`Synced`, and a Root resync is safe. After validation, run
`./scripts/restore-local-gitops-head.sh`. Stable Git values remain `HEAD`; no
feature branch name is committed to them.

Debug-only render inspection:

```bash
helm template local-platform clusters/local/platform
```

## Multi-Repository Extension

In production, a platform repository may manage Applications that point to multiple service repositories.

Example:

```text
platform-config-repo
  |
  +-- service-a Application -> service-a repo
  +-- service-b Application -> service-b repo
  +-- monitoring Application -> platform repo
```

An Argo CD Application is best understood as:

```text
one source repo + one path/chart + one target cluster/namespace
```

It is not necessarily one Application per repository. It is one Application per deployment unit.
