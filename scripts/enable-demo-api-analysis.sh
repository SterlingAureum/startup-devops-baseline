#!/usr/bin/env bash
set -euo pipefail

VALUES_FILE="${VALUES_FILE:-apps/demo-api/helm/values.yaml}"

if [ ! -f "$VALUES_FILE" ]; then
  echo "values file not found: $VALUES_FILE" >&2
  exit 1
fi

python3 - "$VALUES_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

new_steps = '''      steps:
        - setWeight: 20
        - pause:
            duration: 60s
        - analysis:
            templates:
              - templateName: demo-api-canary-health
        - setWeight: 50
        - pause: {}
        - setWeight: 100
'''

lines = text.splitlines(keepends=True)
out = []
i = 0
replaced = False

while i < len(lines):
    line = lines[i]
    if line.strip() == "steps:" and line.startswith("      "):
        out.append(new_steps)
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() == "":
                i += 1
                continue
            if nxt.startswith("        "):
                i += 1
                continue
            break
        replaced = True
        continue

    out.append(line)
    i += 1

if not replaced:
    raise SystemExit("failed to find rollout.strategy.canary.steps block")

text = "".join(out)

if "\nanalysis:\n" not in text:
    text = text.rstrip() + '''

analysis:
  enabled: true
  prometheus:
    address: http://prometheus.monitoring.svc.cluster.local:9090
  metrics:
    canaryTargetUp:
      interval: 15s
      count: 2
      failureLimit: 1
''' + "\n"

path.write_text(text)
print(f"updated {path}")
PY

echo "Analysis has been enabled in ${VALUES_FILE}."
echo "Review the diff before committing:"
echo "  git diff ${VALUES_FILE}"
