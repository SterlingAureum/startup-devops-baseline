# Local application composition

This parent chart composes Argo CD Applications for the local platform and demo.
Its location and external chart pins are preserved; it is not exclusively a
platform-component chart.

The current operator is `python3 scripts/ops/cli.py --env local COMMAND`;
`scripts/ops/local.py` remains a kind-only entrypoint. See
[the local workflow](../../../docs/operations/local.md).

Deploy fetches and pins the root and same-repository child Applications to a
pushed commit. Application images come from GitOps configuration. Optional
`scripts/examples/demo_api.py` builds a clean checkout's matching local image;
its explicit overrides include the tag, source commit and version and clear
the demo chart's cloud digest. External controller
charts retain their declared versions. The repository has not revalidated every
external chart/controller combination live during this restructuring.

Historical feature-revision, failure-recovery and log/trace rehearsal notes are
under `archive/v0.12/`; they are not required for current CI or local commands.
