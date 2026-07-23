#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT=${CODESTRA_BACKUP_ROOT:-/opt/codestra/backups/scheduled}
RETENTION_DAYS=${CODESTRA_BACKUP_RETENTION_DAYS:-35}
MIN_VALID=${CODESTRA_BACKUP_MIN_VALID:-2}

[[ "$RETENTION_DAYS" =~ ^[0-9]+$ && "$MIN_VALID" =~ ^[0-9]+$ ]] || exit 2
mapfile -d '' -t valid_dirs < <(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' -print0 |
        sort -z |
        while IFS= read -r -d '' directory; do
            (cd "$directory" && sha256sum -c SHA256SUMS >/dev/null 2>&1) &&
                printf '%s\0' "$directory"
        done
)

((${#valid_dirs[@]} >= MIN_VALID)) || {
    echo "refusing cleanup: fewer than ${MIN_VALID} verified backups" >&2
    exit 1
}

delete_limit=$((${#valid_dirs[@]} - MIN_VALID))
deleted=0
for directory in "${valid_dirs[@]}"; do
    (( deleted < delete_limit )) || break
    if find "$directory" -maxdepth 0 -mtime "+${RETENTION_DAYS}" | grep -q .; then
        printf 'eligible_for_operator_removal=%s\n' "$directory"
        deleted=$((deleted + 1))
    fi
done

printf 'cleanup_mode=report_only verified=%s protected_minimum=%s eligible=%s\n' \
    "${#valid_dirs[@]}" "$MIN_VALID" "$deleted"
