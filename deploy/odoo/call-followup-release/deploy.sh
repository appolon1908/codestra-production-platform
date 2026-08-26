#!/usr/bin/env bash
set -Eeuo pipefail

ENVIRONMENT="${1:-}"
if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
  echo "usage: $0 staging|production" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PACKAGE="deploy/odoo/call-followup-release"
EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT/reports/odoo-call-followup}"
mkdir -p "$EVIDENCE_DIR"

require_value() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR=MISSING_${name}" >&2
    exit 1
  fi
}

require_exact() {
  local name="$1"
  local expected="$2"
  require_value "$name"
  if [[ "${!name}" != "$expected" ]]; then
    echo "ERROR=${name}_MUST_EQUAL_${expected}" >&2
    exit 1
  fi
}

# Production image format: repository@sha256:<64 lowercase hex>.
require_value ODOO_CALL_FOLLOWUP_IMAGE
require_value ODOO_CALL_FOLLOWUP_RELEASE_SHA
require_value APPROVED_HEAD_SHA
require_value ODOO_DATABASE
require_value MODULE_OPERATION
require_value DATABASE_BACKUP_ID
require_value FILESTORE_BACKUP_ID

if [[ ! "$ODOO_CALL_FOLLOWUP_IMAGE" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR=IMAGE_MUST_BE_IMMUTABLE_REPOSITORY_AT_SHA256" >&2
  exit 1
fi
if [[ ! "$ODOO_CALL_FOLLOWUP_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR=INVALID_RELEASE_SHA" >&2
  exit 1
fi
if [[ "$ODOO_CALL_FOLLOWUP_RELEASE_SHA" != "$APPROVED_HEAD_SHA" ]]; then
  echo "ERROR=RELEASE_SHA_DOES_NOT_MATCH_APPROVED_HEAD" >&2
  exit 1
fi

CURRENT_HEAD="$(git rev-parse HEAD)"
if [[ "$CURRENT_HEAD" != "$APPROVED_HEAD_SHA" ]]; then
  echo "ERROR=CHECKED_OUT_HEAD_DOES_NOT_MATCH_APPROVED_HEAD" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR=WORKTREE_NOT_CLEAN" >&2
  exit 1
fi

case "$MODULE_OPERATION" in
  install)
    MIGRATION_FILE="$PACKAGE/compose.install.yaml"
    ;;
  upgrade)
    MIGRATION_FILE="$PACKAGE/compose.upgrade.yaml"
    ;;
  *)
    echo "ERROR=MODULE_OPERATION_MUST_BE_INSTALL_OR_UPGRADE" >&2
    exit 1
    ;;
esac

if [[ "$ENVIRONMENT" == "production" ]]; then
  BASE_COMPOSE_FILES="${BASE_COMPOSE_FILES:-deploy/odoo/compose.production.yaml}"
  require_exact REQUIRED_CHECKS PASS
  require_exact INDEPENDENT_REVIEW APPROVED
  require_exact STAGING_ACCEPTANCE PASS
  require_exact ROLLBACK_REHEARSAL PASS
  require_exact ALLOW_PRODUCTION_DEPLOY YES
  require_value CHANGE_ID
  require_value ROLLBACK_IMAGE
  require_value ROLLBACK_APP_SHA
  require_exact PRODUCTION_CONFIRMATION "DEPLOY ${APPROVED_HEAD_SHA}"
  if [[ ! "$ROLLBACK_IMAGE" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
    echo "ERROR=ROLLBACK_IMAGE_MUST_BE_IMMUTABLE" >&2
    exit 1
  fi
  if [[ ! "$ROLLBACK_APP_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR=INVALID_ROLLBACK_APP_SHA" >&2
    exit 1
  fi
else
  require_value BASE_COMPOSE_FILES
fi

IFS=':' read -r -a BASE_FILES <<<"$BASE_COMPOSE_FILES"
COMPOSE_ARGS=()
for file in "${BASE_FILES[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR=BASE_COMPOSE_FILE_NOT_FOUND:$file" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "$file")
done
COMPOSE_ARGS+=(-f "$PACKAGE/compose.release.yaml")

if [[ "${INCLUDE_AUTOMATION_SECRETS:-NO}" == "YES" ]]; then
  require_value ODOO_CALL_FOLLOWUP_AUTOMATION_API_KEY_FILE
  require_value ODOO_CALL_FOLLOWUP_AUTOMATION_WEBHOOK_SECRET_FILE
  COMPOSE_ARGS+=(-f "$PACKAGE/compose.automation-secrets.yaml")
elif [[ "${INCLUDE_AUTOMATION_SECRETS:-NO}" != "NO" ]]; then
  echo "ERROR=INCLUDE_AUTOMATION_SECRETS_MUST_BE_YES_OR_NO" >&2
  exit 1
fi

docker compose "${COMPOSE_ARGS[@]}" config >/dev/null

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_FILE="$EVIDENCE_DIR/${ENVIRONMENT}-${TIMESTAMP}.log"
exec > >(tee -a "$EVIDENCE_FILE") 2>&1

echo "ENVIRONMENT=$ENVIRONMENT"
echo "APPROVED_HEAD_SHA=$APPROVED_HEAD_SHA"
echo "ODOO_CALL_FOLLOWUP_IMAGE=$ODOO_CALL_FOLLOWUP_IMAGE"
echo "ODOO_DATABASE=$ODOO_DATABASE"
echo "MODULE_OPERATION=$MODULE_OPERATION"
echo "DATABASE_BACKUP_ID=$DATABASE_BACKUP_ID"
echo "FILESTORE_BACKUP_ID=$FILESTORE_BACKUP_ID"
echo "CHANGE_ID=${CHANGE_ID:-STAGING}"
echo "AUTOMATION_SECRET_OVERLAY=${INCLUDE_AUTOMATION_SECRETS:-NO}"
echo "AUTOMATION_REMOTE_DELIVERY_ENABLED=NO_UNLESS_SEPARATELY_APPROVED_IN_ODOO"

docker compose "${COMPOSE_ARGS[@]}" pull odoo
docker compose "${COMPOSE_ARGS[@]}" ps
docker compose "${COMPOSE_ARGS[@]}" stop odoo

set +e
docker compose \
  "${COMPOSE_ARGS[@]}" \
  -f "$MIGRATION_FILE" \
  run --rm --no-deps odoo
MIGRATION_STATUS=$?
set -e
if [[ "$MIGRATION_STATUS" -ne 0 ]]; then
  echo "MIGRATION=FAIL"
  echo "ODOO_REMAINS_STOPPED=YES"
  echo "ROLLBACK_REQUIRED=YES"
  exit "$MIGRATION_STATUS"
fi
echo "MIGRATION=PASS"

docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps odoo

CONTAINER_ID="$(docker compose "${COMPOSE_ARGS[@]}" ps -q odoo)"
if [[ -z "$CONTAINER_ID" ]]; then
  echo "ERROR=ODOO_CONTAINER_NOT_CREATED" >&2
  exit 1
fi

HEALTHY=NO
for _ in $(seq 1 60); do
  STATUS="$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$CONTAINER_ID"
  )"
  echo "ODOO_STATUS=$STATUS"
  if [[ "$STATUS" == "healthy" || "$STATUS" == "running" ]]; then
    HEALTHY=YES
    break
  fi
  if [[ "$STATUS" == "exited" || "$STATUS" == "dead" ]]; then
    break
  fi
  sleep 5
done

if [[ "$HEALTHY" != "YES" ]]; then
  docker compose "${COMPOSE_ARGS[@]}" logs --no-color --tail=300 odoo
  docker compose "${COMPOSE_ARGS[@]}" stop odoo
  echo "HEALTHCHECK=FAIL"
  echo "ROLLBACK_REQUIRED=YES"
  exit 1
fi

docker inspect --format 'REQUESTED_IMAGE={{.Config.Image}}' "$CONTAINER_ID"
docker inspect --format 'IMAGE_ID={{.Image}}' "$CONTAINER_ID"
docker compose "${COMPOSE_ARGS[@]}" ps
docker compose "${COMPOSE_ARGS[@]}" logs --no-color --tail=200 odoo

echo "HEALTHCHECK=PASS"
echo "SYNTHETIC_CANARY_REQUIRED=YES"
echo "PRODUCTION_DEPLOYMENT_COMPLETE=NO_UNTIL_CANARY_AND_MONITORING_PASS"
echo "EVIDENCE_FILE=$EVIDENCE_FILE"
