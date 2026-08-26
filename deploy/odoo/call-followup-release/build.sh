#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

DOCKERFILE="deploy/odoo/call-followup-release/Dockerfile"
METADATA_FILE="${METADATA_FILE:-$ROOT/build-metadata.call-followup.json}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/appolon1908-hue/codestra-odoo-call-followup}"
PLATFORM="${PLATFORM:-linux/amd64}"
PUSH="${PUSH:-false}"
ODOO_BASE_IMAGE="${ODOO_BASE_IMAGE:-odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5}"

HEAD_SHA="$(git rev-parse HEAD)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR=WORKTREE_NOT_CLEAN" >&2
  exit 1
fi
if [[ ! "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR=INVALID_HEAD_SHA" >&2
  exit 1
fi
if [[ "$IMAGE_REPOSITORY" == *":latest" || "$IMAGE_REPOSITORY" == *"@sha256:"* ]]; then
  echo "ERROR=IMAGE_REPOSITORY_MUST_BE_UNTAGGED_REPOSITORY" >&2
  exit 1
fi
if [[ "$ODOO_BASE_IMAGE" != *@sha256:* ]]; then
  echo "ERROR=BASE_IMAGE_MUST_BE_DIGEST_PINNED" >&2
  exit 1
fi

IMAGE_TAG="${IMAGE_REPOSITORY}:${HEAD_SHA}"
BUILD_ARGS=(
  docker buildx build "$ROOT"
  --file "$DOCKERFILE"
  --platform "$PLATFORM"
  --pull
  --build-arg "ODOO_BASE_IMAGE=$ODOO_BASE_IMAGE"
  --build-arg "VCS_REF=$HEAD_SHA"
  --build-arg "BUILD_DATE=$BUILD_DATE"
  --tag "$IMAGE_TAG"
  --metadata-file "$METADATA_FILE"
)

if [[ "$PUSH" == "true" ]]; then
  BUILD_ARGS+=(--push --provenance=mode=max --sbom=true)
elif [[ "$PUSH" == "false" ]]; then
  BUILD_ARGS+=(--load --provenance=false --sbom=false)
else
  echo "ERROR=PUSH_MUST_BE_TRUE_OR_FALSE" >&2
  exit 1
fi

"${BUILD_ARGS[@]}"

echo "IMAGE_TAG=$IMAGE_TAG"
echo "BUILD_METADATA=$METADATA_FILE"

if [[ "$PUSH" == "true" ]]; then
  DIGEST="$(
    python3 - "$METADATA_FILE" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
digest = data.get("containerimage.digest", "")
if not digest.startswith("sha256:") or len(digest) != 71:
    raise SystemExit("release build metadata did not contain an image digest")
print(digest)
PY
  )"
  echo "IMMUTABLE_IMAGE=${IMAGE_REPOSITORY}@${DIGEST}"
else
  echo "ATTESTATIONS_PERSISTED=NO_LOCAL_LOAD"
  echo "RELEASE_PUSH_REQUIRED_FOR_SBOM_AND_PROVENANCE=YES"
fi
