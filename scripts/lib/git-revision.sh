#!/usr/bin/env bash

resolve_remote_git_revision() {
  local repo_url="$1"
  local requested_revision="$2"
  local remote_result
  local resolved_revision

  if [[ "${requested_revision}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s\n' "${requested_revision,,}"
    return 0
  fi

  if ! remote_result="$(git ls-remote --exit-code "${repo_url}" "refs/heads/${requested_revision}" 2>/dev/null)"; then
    echo "ERROR: remote feature branch not found: ${requested_revision}" >&2
    echo "Push the branch before running GitOps acceptance." >&2
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
