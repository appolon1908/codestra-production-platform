#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PACKAGE="deploy/odoo/call-followup-release"
python3 scripts/validate_odoo_call_followup_docker_release.py

for script in "$PACKAGE/build.sh" "$PACKAGE/validate.sh" "$PACKAGE/deploy.sh"; do
  bash -n "$script"
done

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR=DOCKER_COMPOSE_V2_REQUIRED" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
: >"$TMP_DIR/api_key"
: >"$TMP_DIR/webhook_secret"

export ODOO_CALL_FOLLOWUP_IMAGE="ghcr.io/codestra/test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export ODOO_CALL_FOLLOWUP_RELEASE_SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export ODOO_DATABASE="odoo_validation"
export ODOO_CALL_FOLLOWUP_AUTOMATION_API_KEY_FILE="$TMP_DIR/api_key"
export ODOO_CALL_FOLLOWUP_AUTOMATION_WEBHOOK_SECRET_FILE="$TMP_DIR/webhook_secret"

BASE="deploy/odoo/compose.production.yaml"
docker compose -f "$BASE" -f "$PACKAGE/compose.release.yaml" config >/dev/null
docker compose -f "$BASE" -f "$PACKAGE/compose.release.yaml" -f "$PACKAGE/compose.install.yaml" config >/dev/null
docker compose -f "$BASE" -f "$PACKAGE/compose.release.yaml" -f "$PACKAGE/compose.upgrade.yaml" config >/dev/null
docker compose -f "$BASE" -f "$PACKAGE/compose.release.yaml" -f "$PACKAGE/compose.automation-secrets.yaml" config >/dev/null

echo "ODOO_CALL_FOLLOWUP_DOCKER_RELEASE_VALIDATION=PASS"
