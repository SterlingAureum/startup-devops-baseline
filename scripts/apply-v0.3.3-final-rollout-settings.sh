#!/usr/bin/env bash
set -euo pipefail

VALUES_FILE="${VALUES_FILE:-apps/demo-api/helm/values.yaml}"

if [ ! -f "$VALUES_FILE" ]; then
  echo "values file not found: ${VALUES_FILE}" >&2
  exit 1
fi

python3 - "$VALUES_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

if "maxSurge:" in text or "maxUnavailable:" in text:
    print(f"{path}: maxSurge/maxUnavailable already present; no change made.")
    raise SystemExit(0)

lines = text.splitlines(keepends=True)
out = []
inserted = False

for idx, line in enumerate(lines):
    out.append(line)

    # Expected current structure:
    # rollout:
    #   strategy:
    #     canary:
    #
    # Insert immediately after the canary: line at 4 spaces indentation.
    if line.startswith("    canary:") and line.strip() == "canary:":
        out.append("      # Keep rollout resource overhead bounded during canary updates.\n")
        out.append("      # Important for memory-heavy or GPU workloads.\n")
        out.append("      maxSurge: 1\n")
        out.append("      maxUnavailable: 0\n")
        inserted = True

if not inserted:
    raise SystemExit(
        "failed to find rollout.strategy.canary block. "
        "Please merge apps/demo-api/helm/values-v0.3.3-final-optimization-snippet.yaml manually."
    )

path.write_text("".join(out))
print(f"updated {path}")
PY

echo
echo "Review the result:"
echo "  git diff ${VALUES_FILE}"
echo
echo "Then validate:"
echo "  helm lint apps/demo-api/helm"
echo "  helm template demo-api apps/demo-api/helm | grep -E 'maxSurge|maxUnavailable|kind: AnalysisTemplate|analysis:' -A10"
