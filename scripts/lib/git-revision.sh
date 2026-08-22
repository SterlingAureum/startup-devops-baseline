#!/usr/bin/env bash

resolve_remote_git_revision() {
  local repo_url="$1"
  local requested_revision="$2"
  local remote_result
  local remote_selector
  local resolved_revision

  if [[ "${requested_revision}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s\n' "${requested_revision,,}"
    return 0
  fi

  if [ "${requested_revision}" = "HEAD" ]; then
    remote_selector="HEAD"
  else
    remote_selector="refs/heads/${requested_revision}"
  fi

  if ! remote_result="$(git ls-remote --exit-code "${repo_url}" "${remote_selector}" 2>/dev/null)"; then
    echo "ERROR: remote Git revision not found: ${requested_revision}" >&2
    echo "Push the revision before running GitOps reconciliation." >&2
    return 1
  fi

  if [ "$(wc -l <<<"${remote_result}")" -ne 1 ]; then
    echo "ERROR: remote revision is ambiguous: ${requested_revision}" >&2
    return 1
  fi

  resolved_revision="$(awk '{print $1}' <<<"${remote_result}")"
  if ! [[ "${resolved_revision}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "ERROR: remote revision did not resolve to a full commit SHA: ${requested_revision}" >&2
    return 1
  fi

  printf '%s\n' "${resolved_revision,,}"
}

assert_remote_git_revision_contains_path() {
  local repo_url="$1"
  local requested_revision="$2"
  local resolved_revision="$3"
  local required_path="$4"

  if ! [[ "${resolved_revision}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: source preflight requires a full lowercase commit SHA." >&2
    return 1
  fi

  case "${required_path}" in
    ""|/*|*..*|*:*)
      echo "ERROR: unsafe required Git path: ${required_path}" >&2
      return 1
      ;;
  esac

  if ! git fetch --quiet --no-tags "${repo_url}" "${requested_revision}" >/dev/null 2>&1; then
    echo "ERROR: unable to fetch remote Git revision for source preflight: ${requested_revision}" >&2
    return 1
  fi

  if ! git cat-file -e "${resolved_revision}:${required_path}" 2>/dev/null; then
    echo "ERROR: target revision does not contain required source path: ${required_path}" >&2
    echo "Requested revision: ${requested_revision}" >&2
    echo "Resolved commit:   ${resolved_revision}" >&2
    echo "No Kubernetes resource was changed." >&2
    return 1
  fi
}
