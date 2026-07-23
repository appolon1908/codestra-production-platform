#!/usr/bin/env bash
set -euo pipefail
umask 077

BACKUP_ROOT=${CODESTRA_BACKUP_ROOT:-/opt/codestra/backups/scheduled}
RECIPIENT=${CODESTRA_BACKUP_GPG_RECIPIENT:-}
REMOTE_HOST=${CODESTRA_BACKUP_REMOTE_HOST:-}
REMOTE_DIR=${CODESTRA_BACKUP_REMOTE_DIR:-}
SSH_IDENTITY=${CODESTRA_BACKUP_SSH_IDENTITY:-}
KNOWN_HOSTS=${CODESTRA_BACKUP_KNOWN_HOSTS:-}
ALERT_URL=${CODESTRA_BACKUP_ALERT_URL:-}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK_DIR="${BACKUP_ROOT}/.work-${STAMP}"
FINAL_DIR="${BACKUP_ROOT}/${STAMP}"
PAUSED=()

notify() {
    local state=$1
    local detail=$2
    [[ -z "$ALERT_URL" ]] && return 0
    curl --fail --silent --show-error --max-time 10 \
        -H 'Content-Type: application/json' \
        --data "{\"service\":\"codestra-backup\",\"state\":\"${state}\",\"timestamp\":\"${STAMP}\",\"detail\":\"${detail}\"}" \
        "$ALERT_URL" >/dev/null
}

fail() {
    local line=$1
    notify failure "backup failed at line ${line}" || true
}

resume_services() {
    local name
    for name in "${PAUSED[@]}"; do
        docker unpause "$name" >/dev/null 2>&1 || true
    done
}

cleanup_work_dir() {
    resume_services
    case "$WORK_DIR" in
        "$BACKUP_ROOT"/.work-20*T*Z)
            [[ ! -L "$WORK_DIR" ]] && rm -rf -- "$WORK_DIR"
            ;;
        *)
            echo "refusing unsafe work-directory cleanup" >&2
            return 1
            ;;
    esac
}

trap 'fail "$LINENO"; cleanup_work_dir' ERR
trap cleanup_work_dir EXIT

required=(docker gpg sha256sum tar scp)
for command_name in "${required[@]}"; do
    command -v "$command_name" >/dev/null || {
        echo "required command unavailable: ${command_name}" >&2
        exit 2
    }
done

for value_name in RECIPIENT REMOTE_HOST REMOTE_DIR SSH_IDENTITY KNOWN_HOSTS; do
    [[ -n "${!value_name}" ]] || {
        echo "required protected configuration missing: ${value_name}" >&2
        exit 2
    }
done

[[ -r "$SSH_IDENTITY" && -r "$KNOWN_HOSTS" ]] || {
    echo "SSH identity or known-hosts file is not readable" >&2
    exit 2
}
gpg --batch --list-keys "$RECIPIENT" >/dev/null 2>&1 || {
    echo "configured backup encryption recipient is unavailable" >&2
    exit 2
}

mkdir -p "$WORK_DIR" "$FINAL_DIR"
chmod 0700 "$WORK_DIR" "$FINAL_DIR"

for service in codestra-odoo-1 codestra-n8n-1 codestra-middleware-1 codestra-identity-keycloak-1; do
    docker inspect "$service" >/dev/null
    docker pause "$service" >/dev/null
    PAUSED+=("$service")
done

docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_odoo \
    -f /tmp/codestra-backup-odoo.dump
docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_middleware \
    -f /tmp/codestra-backup-middleware.dump
docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_n8n \
    -f /tmp/codestra-backup-n8n.dump
docker exec codestra-identity-identity-db-1 pg_dump -U keycloak -Fc keycloak \
    -f /tmp/codestra-backup-keycloak.dump

docker cp codestra-postgres-1:/tmp/codestra-backup-odoo.dump "$WORK_DIR/odoo.dump"
docker cp codestra-postgres-1:/tmp/codestra-backup-middleware.dump "$WORK_DIR/middleware.dump"
docker cp codestra-postgres-1:/tmp/codestra-backup-n8n.dump "$WORK_DIR/n8n.dump"
docker cp codestra-identity-identity-db-1:/tmp/codestra-backup-keycloak.dump "$WORK_DIR/keycloak.dump"

docker run --rm \
    -v codestra_odoo_data:/source/odoo:ro \
    -v codestra_n8n_data:/source/n8n:ro \
    -v codestra_identity_identity_postgres_data:/source/identity:ro \
    -v "$WORK_DIR":/backup \
    alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce \
    sh -ec 'tar -czf /backup/application-volumes.tar.gz -C /source odoo n8n'

tar --exclude='env' --exclude='secrets' --exclude='*.env' \
    -czf "$WORK_DIR/configuration.tar.gz" -C /opt codestra
tar -czf "$WORK_DIR/protected-runtime-secrets.tar.gz" \
    -C /opt/codestra env \
    -C /etc/codestra secrets

resume_services
PAUSED=()

(
    cd "$WORK_DIR"
    sha256sum ./* > SHA256SUMS
    sha256sum -c SHA256SUMS
)
tar -czf "$WORK_DIR/codestra-${STAMP}.tar.gz" -C "$WORK_DIR" \
    odoo.dump middleware.dump n8n.dump keycloak.dump \
    application-volumes.tar.gz configuration.tar.gz \
    protected-runtime-secrets.tar.gz SHA256SUMS
gpg --batch --yes --trust-model always --recipient "$RECIPIENT" \
    --output "$FINAL_DIR/codestra-${STAMP}.tar.gz.gpg" \
    --encrypt "$WORK_DIR/codestra-${STAMP}.tar.gz"
sha256sum "$FINAL_DIR/codestra-${STAMP}.tar.gz.gpg" \
    > "$FINAL_DIR/SHA256SUMS"
(
    cd "$FINAL_DIR"
    sha256sum -c SHA256SUMS
)

scp -q -i "$SSH_IDENTITY" \
    -o BatchMode=yes \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS" \
    "$FINAL_DIR/codestra-${STAMP}.tar.gz.gpg" \
    "$FINAL_DIR/SHA256SUMS" \
    "${REMOTE_HOST}:${REMOTE_DIR}/${STAMP}/"

printf '%s\n' "$STAMP" > "$BACKUP_ROOT/LAST_SUCCESS"
notify success "encrypted backup and replication completed"
printf 'BACKUP_STATUS=PASS\nBACKUP_TIMESTAMP=%s\nBACKUP_DIRECTORY=%s\n' \
    "$STAMP" "$FINAL_DIR"
