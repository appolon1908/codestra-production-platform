#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT=${CODESTRA_BACKUP_ROOT:-/opt/codestra/backups/scheduled}
MAX_AGE_SECONDS=${CODESTRA_BACKUP_MAX_AGE_SECONDS:-93600}
MIN_FREE_BYTES=${CODESTRA_BACKUP_MIN_FREE_BYTES:-10737418240}
REQUIRE_EVIDENCE=${CODESTRA_BACKUP_REQUIRE_EVIDENCE:-false}

[[ "$MAX_AGE_SECONDS" =~ ^[0-9]+$ && "$MIN_FREE_BYTES" =~ ^[0-9]+$ ]] || {
    echo "numeric backup thresholds required" >&2
    exit 2
}
[[ -r "$BACKUP_ROOT/LAST_SUCCESS" ]] || {
    echo "backup_last_success_missing 1"
    exit 1
}

last_success=$(<"$BACKUP_ROOT/LAST_SUCCESS")
[[ "$last_success" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
    echo "backup_last_success_malformed 1"
    exit 1
}
if [[ "$REQUIRE_EVIDENCE" == true ]]; then
    backup_dir="$BACKUP_ROOT/$last_success"
    [[ -d "$backup_dir" && ! -L "$backup_dir" && -f "$backup_dir/EVIDENCE-SHA256SUMS" && ! -L "$backup_dir/EVIDENCE-SHA256SUMS" ]] || {
        echo "backup_evidence_missing_or_unsafe 1"
        exit 1
    }
    (cd "$backup_dir" && sha256sum -c EVIDENCE-SHA256SUMS >/dev/null) || {
        echo "backup_evidence_invalid 1"
        exit 1
    }
elif [[ "$REQUIRE_EVIDENCE" != false ]]; then
    echo "backup evidence mode must be true or false" >&2
    exit 2
fi
last_epoch=$(date -u -d "${last_success:0:8} ${last_success:9:2}:${last_success:11:2}:${last_success:13:2}" +%s)
now_epoch=$(date -u +%s)
age=$((now_epoch - last_epoch))
free_bytes=$(df --output=avail -B1 "$BACKUP_ROOT" | tail -1 | tr -d ' ')

printf 'backup_age_seconds %s\nbackup_free_bytes %s\n' "$age" "$free_bytes"
(( age <= MAX_AGE_SECONDS )) || exit 1
(( free_bytes >= MIN_FREE_BYTES )) || exit 1
