#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
source_file=${CODESTRA_STAGING_METRICS_SECRET_SOURCE:-/opt/codestra/secrets/identity-staging/monitoring-readonly-client-secret}
target_file=${CODESTRA_STAGING_METRICS_SECRET_TARGET:-/etc/codestra/secrets/monitoring-runtime/staging_metrics_client_secret}
[[ -f "$source_file" && ! -L "$source_file" && "$source_file" != "$target_file" ]]
install -d -o root -g 65534 -m 0750 "${target_file%/*}"
temporary=$(mktemp "${target_file%/*}/.staging_metrics_client_secret.XXXXXX")
trap 'find "$temporary" -delete 2>/dev/null || true' EXIT
install -o root -g 65534 -m 0640 "$source_file" "$temporary"
cmp -s "$source_file" "$temporary"
mv "$temporary" "$target_file"
trap - EXIT
