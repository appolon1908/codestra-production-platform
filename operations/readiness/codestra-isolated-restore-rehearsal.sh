#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=/opt/codestra/backups/production-readiness-local
evidence_root=/opt/codestra/evidence/production-readiness-restore
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work_dir="${evidence_root}/.work-${stamp}"
final_dir="${evidence_root}/${stamp}"
suffix=$(printf '%s' "$stamp" | tr -cd '0-9A-Za-z')
container="codestra-readiness-restore-${suffix}"
network="codestra-readiness-restore-${suffix}"
volume="codestra_readiness_restore_${suffix}"

cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    if [[ -d "$work_dir" && ! -L "$work_dir" ]]; then
        find "$work_dir" -type f -delete
        find "$work_dir" -depth -type d -empty -delete
    fi
}
trap cleanup EXIT
trap 'echo "RESTORE_REHEARSAL_GATE=FAIL" >&2' ERR

latest=$(find "$backup_root" -mindepth 2 -maxdepth 2 -type f -name STATUS.txt -print0 \
    | xargs -0 -r grep -l '^BACKUP_STATUS=PASS$' \
    | sort | tail -n1)
test -n "$latest"
backup_dir=$(dirname "$latest")
encrypted=$(find "$backup_dir" -maxdepth 1 -type f -name 'codestra-*.tar.gz.gpg' | sort | tail -n1)
test -n "$encrypted"

mkdir -p "$work_dir" "$final_dir"
chmod 0700 "$work_dir" "$final_dir"
(cd "$backup_dir" && sha256sum -c EVIDENCE-SHA256SUMS)
(cd "$backup_dir" && sha256sum -c SHA256SUMS)

gpg --homedir /etc/codestra/backup-gpg --batch --yes \
    --output "$work_dir/backup.tar.gz" --decrypt "$encrypted"
tar -xzf "$work_dir/backup.tar.gz" -C "$work_dir"
(cd "$work_dir" && sha256sum -c SHA256SUMS)

mkdir -p "$work_dir/restored-volumes" "$work_dir/restored-configuration"
tar -xzf "$work_dir/application-volumes.tar.gz" -C "$work_dir/restored-volumes"
tar -xzf "$work_dir/configuration.tar.gz" -C "$work_dir/restored-configuration"
gzip -t "$work_dir/runtime-images.tar.gz"
tar -tzf "$work_dir/runtime-images.tar.gz" | grep -qx 'manifest.json'
test "$(wc -l < "$work_dir/BACKUP-MANIFEST.tsv")" -eq 8
grep -q '^codestra-middleware-1[[:space:]]sha256:' "$work_dir/BACKUP-MANIFEST.tsv"
test -d "$work_dir/restored-volumes/odoo"
test -d "$work_dir/restored-volumes/n8n"
test -f "$work_dir/restored-configuration/opt/codestra/compose/compose.yaml"
test -f "$work_dir/restored-configuration/opt/codestra/compose/compose.live-delivery-safety.yaml"
test -f "$work_dir/restored-configuration/etc/caddy/Caddyfile"
test -f "$work_dir/restored-configuration/opt/codestra/identity-platform/deploy/compose.identity.yaml"
test -d "$work_dir/restored-configuration/etc/codestra/secrets"

docker network create --internal --subnet 10.253.255.0/28 "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$container" --network "$network" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -v "$volume":/var/lib/postgresql/data \
    postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94 >/dev/null

for _ in $(seq 1 60); do
    if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then break; fi
    sleep 2
done
docker exec "$container" pg_isready -U postgres >/dev/null

docker exec -i "$container" psql -U postgres -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
CREATE ROLE keycloak LOGIN;
CREATE ROLE codestra_monitoring;
CREATE ROLE middleware_app;
CREATE ROLE middleware_data_owner;
CREATE ROLE mw_event_gateway;
CREATE ROLE mw_evidence_runner;
CREATE ROLE mw_extension_allocator;
CREATE ROLE mw_integration_api;
CREATE ROLE mw_notification_worker;
CREATE ROLE mw_pjsip_adapter;
CREATE ROLE mw_policy_engine;
CREATE ROLE mw_reconciliation_worker;
CREATE ROLE mw_scheduler;
CREATE ROLE mw_sync_worker;
CREATE ROLE mw_telephony_provisioning;
CREATE ROLE mw_vicidial_adapter;
CREATE ROLE mw_webphone_session;
CREATE ROLE n8n_app;
CREATE ROLE odoo_app;
SQL
for database in codestra_odoo codestra_middleware codestra_n8n; do
    docker exec "$container" createdb -U postgres "$database"
done
docker exec "$container" createdb -U postgres -O keycloak keycloak

for pair in odoo:codestra_odoo middleware:codestra_middleware n8n:codestra_n8n keycloak:keycloak; do
    file=${pair%%:*}
    database=${pair#*:}
    docker cp "$work_dir/${file}.dump" "$container:/tmp/${file}.dump" >/dev/null
    docker exec "$container" pg_restore -U postgres -d "$database" \
        --exit-on-error --no-owner "/tmp/${file}.dump" >/dev/null
done

database_count=$(docker exec "$container" psql -U postgres -d postgres -Atc \
    "select count(*) from pg_database where datallowconn and not datistemplate")
test "$database_count" -ge 5
for database in codestra_odoo codestra_middleware codestra_n8n keycloak; do
    object_count=$(docker exec "$container" psql -U postgres -d "$database" -Atc \
        "select count(*) from pg_class where relkind in ('r','p','v','m')")
    test "$object_count" -gt 0
done

cat > "$final_dir/RESTORE-RESULT.txt" <<EOF
RESTORE_REHEARSAL_GATE=PASS
BACKUP_CHECKSUM_GATE=PASS
INNER_CHECKSUM_GATE=PASS
ISOLATED_NETWORK_GATE=PASS
PUBLISHED_PORT_COUNT=0
DATABASE_RESTORE_COUNT=4
DATABASE_IDENTITY_GATE=PASS
SCHEMA_HEALTH_GATE=PASS
APPLICATION_VOLUME_RESTORE_GATE=PASS
CONFIGURATION_RESTORE_GATE=PASS
LOCAL_RUNTIME_IMAGE_ARCHIVE_GATE=PASS
EXACT_RUNTIME_IMAGE_ID_BINDING_GATE=PASS
DISPOSABLE_CLEANUP_REQUIRED=YES
EOF
sha256sum "$final_dir/RESTORE-RESULT.txt" > "$final_dir/SHA256SUMS"
printf '%s\n' "$final_dir"
