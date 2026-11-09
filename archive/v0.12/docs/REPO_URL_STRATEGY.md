# Repository URL Strategy

The repository currently represents a personal DevOps portfolio baseline.

For v0.2, Application manifests keep the repository URL explicitly configured.

Reason:

- The repository is not distributed as a generic template.
- Explicit URLs keep the GitOps flow simple and predictable.
- Future reusable templates can introduce environment rendering or ApplicationSet patterns.

If this repository evolves into a reusable platform template, repoURL injection can be introduced later.
