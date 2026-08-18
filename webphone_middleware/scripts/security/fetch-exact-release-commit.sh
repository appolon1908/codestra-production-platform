#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:-}"
remote="${2:-origin}"

if [[ ! "${release_sha}" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'invalid release SHA format\n' >&2
  exit 64
fi

# Fetch only the immutable object being authorized. Do not rely on the
# workflow checkout depth and do not broaden this to the full repository.
git fetch --no-tags --depth=1 "${remote}" "${release_sha}"

fetched_sha="$(git rev-parse --verify 'FETCH_HEAD^{commit}')"
if [[ "${fetched_sha}" != "${release_sha}" ]]; then
  printf 'fetched commit does not match requested release SHA\n' >&2
  exit 65
fi

git cat-file -e "${release_sha}^{commit}"
printf '%s\n' "${fetched_sha}"
