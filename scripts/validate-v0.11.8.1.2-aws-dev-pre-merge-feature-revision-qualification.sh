#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.json"
FEATURE_REVISION="feature/v0.11-observability-sre-baseline"
SUCCESSOR_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"

python3 - "${ROOT_DIR}" "${CONTRACT}" "${FEATURE_REVISION}" "${SUCCESSOR_CONTRACT}" <<'PY'
import json, re, sys
from pathlib import Path

root, contract_path, feature, successor_path = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
contract = json.loads(contract_path.read_text())
successor = json.loads(successor_path.read_text())
expected_apps = [
    "application-admission-policies-aws-dev", "data-platform-network-policy-aws-dev",
    "demo-api-aws-dev", "external-secrets-startup-apps", "namespace-guardrails-aws-dev",
    "observability-views-aws-dev", "postgresql-baseline",
    "runtime-qualification-rbac-aws-dev", "startup-apps-network-policy-aws-dev",
]
assert contract["version"] == "v0.11.8.1.2"
assert contract["predecessor"] == "v0.11.8.1.1"
assert contract["featureRevision"] == feature
assert contract["awsDevSameRepositoryApplications"] == expected_apps
assert contract["sourcePolicy"] == {
    "rootRevisionSelectedByDeployScript": True,
    "awsDevSameRepositoryChildren": feature,
    "awsTestSameRepositoryChildren": "main",
    "awsProdSameRepositoryChildren": "main",
    "externalChartVersionsPreserved": True,
}
assert contract["preMergeRestoration"]["required"] is True
assert contract["preMergeRestoration"]["mergeBlockedByFeatureResidue"] is True
assert contract["scope"]["mainMergeRequiredForFeatureQualification"] is False
assert contract["scope"]["runtimeMutationAddedToChecker"] is False
assert successor["version"] == "v0.11.9.3.2"
assert successor["predecessor"] == "v0.11.9.3.1"
assert successor["implementationBaselineCommit"] == "cf2c7cd37c114e875b731fb151a05aad9b9cddd6"
assert successor["activeRevisionPolicy"]["awsDevSameRepositoryChildren"] == "main"
assert successor["historicalPreview"]["active"] is False

overlay = (root / "clusters/aws/overlays/dev/kustomization.yaml").read_text()
assert feature not in overlay
assert "path: /spec/source/targetRevision" not in overlay
assert "name: monitoring-aws-dev" in overlay
for env in ("test", "prod"):
    assert feature not in (root / f"clusters/aws/overlays/{env}/kustomization.yaml").read_text()

live = (root / "scripts/check-aws-dev-observability-qualification.sh").read_text()
for marker in (
    'EXPECTED_GIT_TARGET_REVISION="${EXPECTED_GIT_TARGET_REVISION:-main}"',
    '.spec.source.targetRevision == $source_revision',
    '.status.sync.revision == $revision',
    '--arg git_target_revision "${EXPECTED_GIT_TARGET_REVISION}"',
    'observedValue: $git_target_revision',
):
    assert marker in live, marker
for app in expected_apps:
    assert re.search(rf"^  {re.escape(app)}$", live, re.M), app
for forbidden in ("kubectl apply", "kubectl patch", "argocd app sync", "kubectl delete"):
    assert forbidden not in live

boundary = (root / "scripts/check-aws-gitops-revision-boundary.sh").read_text()
for marker in ("EXPECTED_DEV_GIT_TARGET_REVISION:-main", "EXPECTED_TEST_GIT_TARGET_REVISION:-main", "EXPECTED_PROD_GIT_TARGET_REVISION:-main",
               '"kube-prometheus-stack": "88.5.0"', '"karpenter": "1.14.0"'):
    assert marker in boundary, marker
assert "EXPECTED_DEV_GIT_TARGET_REVISION:-feature/" not in boundary

for relative, marker in (
    ("README.md", "v0.11.8.1.2"), ("CHANGELOG.md", "## v0.11.8.1.2"),
    ("docs/ROADMAP.md", "v0.11.8.1.2"), ("docs/OBSERVABILITY.md", "v0.11.8.1.2"),
    ("docs/TROUBLESHOOTING.md", "split revision"),
    (".github/CODEOWNERS", "/scripts/check-aws-gitops-revision-boundary.sh"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.sh"),
):
    assert marker in (root / relative).read_text(), relative

for mutation in (
    lambda x: x["sourcePolicy"].__setitem__("awsTestSameRepositoryChildren", feature),
    lambda x: x["sourcePolicy"].__setitem__("externalChartVersionsPreserved", False),
    lambda x: x["preMergeRestoration"].__setitem__("required", False),
    lambda x: x["scope"].__setitem__("mainMergeRequiredForFeatureQualification", True),
):
    changed = json.loads(contract_path.read_text()); mutation(changed)
    assert changed != contract
print("v0.11.8.1.2 historical feature contract and v0.11.9.3.2 main-restoration successor passed.")
PY

bash -n "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh"
bash -n "${ROOT_DIR}/scripts/check-aws-dev-observability-qualification.sh"

FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_DIR}"' EXIT
mkdir -p "${FIXTURE_DIR}/bin"
cat >"${FIXTURE_DIR}/bin/kustomize" <<'PY'
#!/usr/bin/env python3
import os, sys
env = sys.argv[-1].rstrip('/').split('/')[-1]
git_names = ["application-admission-policies", "data-platform-network-policy", "demo-api", "external-secrets-startup-apps", "namespace-guardrails", "observability-views", "postgresql-baseline", "runtime-qualification-rbac", "startup-apps-network-policy"]
if env == "prod": git_names.remove("runtime-qualification-rbac")
rev = "main"
if env == "dev" and os.getenv("FAKE_BAD_DEV_FEATURE") == "true": rev = "feature/v0.11-observability-sre-baseline"
if env == "test" and os.getenv("FAKE_BAD_TEST_FEATURE") == "true": rev = "feature/v0.11-observability-sre-baseline"
charts = {"argo-rollouts":"2.41.1","aws-load-balancer-controller":"1.14.0","plugin-barman-cloud":"0.7.0","cert-manager":"v1.21.0","cloudnative-pg":"0.29.0","external-secrets":"2.8.0","karpenter":"1.14.0","karpenter-crd":"1.14.0","kube-prometheus-stack":"88.5.0"}
if os.getenv("FAKE_BAD_EXTERNAL") == "true": charts["kube-prometheus-stack"] = "88.5.1"
docs=[]
for name in git_names:
    docs.append(f"apiVersion: argoproj.io/v1alpha1\nkind: Application\nmetadata:\n  name: {name}-{env}\nspec:\n  source:\n    repoURL: https://github.com/SterlingAureum/startup-devops-baseline.git\n    targetRevision: {rev}\n")
for chart, version in charts.items():
    docs.append(f"apiVersion: argoproj.io/v1alpha1\nkind: Application\nmetadata:\n  name: {chart}-{env}\nspec:\n  source:\n    chart: {chart}\n    targetRevision: {version}\n")
print("---\n".join(docs))
PY
chmod +x "${FIXTURE_DIR}/bin/kustomize"
PATH="${FIXTURE_DIR}/bin:${PATH}" "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" >/dev/null
if FAKE_BAD_DEV_FEATURE=true PATH="${FIXTURE_DIR}/bin:${PATH}" "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" >/dev/null 2>&1; then
  echo "Revision-boundary checker accepted feature residue in aws-dev." >&2; exit 1
fi
if FAKE_BAD_TEST_FEATURE=true PATH="${FIXTURE_DIR}/bin:${PATH}" "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" >/dev/null 2>&1; then
  echo "Revision-boundary checker accepted feature residue in aws-test." >&2; exit 1
fi
if FAKE_BAD_EXTERNAL=true PATH="${FIXTURE_DIR}/bin:${PATH}" "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" >/dev/null 2>&1; then
  echo "Revision-boundary checker accepted external Chart drift." >&2; exit 1
fi
echo "v0.11.8.1.2 historical contract plus restored-main positive and negative revision-boundary fixtures passed."
