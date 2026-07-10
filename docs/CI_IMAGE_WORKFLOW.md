# CI Image Workflow

v0.2 introduces a basic CI validation workflow.

Pipeline:

- Helm lint
- Helm template validation
- Docker image build validation

The workflow validates changes before GitOps synchronization.
It does not publish images or deploy workloads yet.
