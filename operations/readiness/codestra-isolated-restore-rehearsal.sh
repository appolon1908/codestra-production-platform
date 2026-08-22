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
odoo_container="codestra-readiness-restore-odoo-${suffix}"
network="codestra-readiness-restore-${suffix}"
volume="codestra_readiness_restore_${suffix}"
rehearsal_started_ns=$(date +%s%N)
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
validator=
for candidate in \
    "$script_dir/../restore/validate_odoo_filestore_pair.py" \
    "$script_dir/../../restore/validate_odoo_filestore_pair.py" \
    /opt/codestra/operations/restore/validate_odoo_filestore_pair.py; do
    if [[ -f "$candidate" && -r "$candidate" ]]; then
        validator=$candidate
        break
    fi
done

cleanup() {
    docker rm -f "$odoo_container" >/dev/null 2>&1 || true
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
test -s "$work_dir/ODOO-BACKUP-METADATA"
test -f "$work_dir/odoo-attachments.tsv"
grep -qx "BACKUP_ID=${backup_dir##*/}" "$work_dir/ODOO-BACKUP-METADATA"
test -n "$validator"
test -f "$work_dir/restored-configuration/opt/codestra/compose/compose.yaml"
test -f "$work_dir/restored-configuration/opt/codestra/compose/compose.live-delivery-safety.yaml"
test -f "$work_dir/restored-configuration/etc/caddy/Caddyfile"
test -f "$work_dir/restored-configuration/opt/codestra/identity-platform/deploy/compose.identity.yaml"
test -d "$work_dir/restored-configuration/etc/codestra/secrets"
gzip -dc "$work_dir/runtime-images.tar.gz" | docker image load >/dev/null
while read -r _ image_id; do
    docker image inspect "$image_id" >/dev/null
done < "$work_dir/BACKUP-MANIFEST.tsv"
materialization_finished_ns=$(date +%s%N)
repository_materialization_ms=$(( (materialization_finished_ns - rehearsal_started_ns) / 1000000 ))

postgres_image=$(awk '$1 == "codestra-postgres-1" {print $2}' "$work_dir/BACKUP-MANIFEST.tsv")
test -n "$postgres_image"
docker image inspect "$postgres_image" >/dev/null
rehearsal_password_file="$work_dir/rehearsal-db-password"
openssl rand -hex 32 > "$rehearsal_password_file"
chmod 0444 "$rehearsal_password_file"
docker network create --internal --subnet 10.253.255.0/28 "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$container" --network "$network" \
    --network-alias postgres \
    -e POSTGRES_PASSWORD_FILE=/run/secrets/rehearsal_db_password \
    -v "$rehearsal_password_file:/run/secrets/rehearsal_db_password:ro" \
    -v "$volume":/var/lib/postgresql/data \
    "$postgres_image" >/dev/null

for _ in $(seq 1 60); do
    if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then break; fi
    sleep 2
done
docker exec "$container" pg_isready -U postgres >/dev/null

docker exec -i "$container" psql -U postgres -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
\set rehearsal_password `cat /run/secrets/rehearsal_db_password`
CREATE ROLE keycloak LOGIN;
CREATE ROLE codestra_monitoring;
CREATE ROLE middleware_app LOGIN;
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
CREATE ROLE n8n_app LOGIN;
CREATE ROLE odoo_app LOGIN PASSWORD :'rehearsal_password';
SQL
docker exec "$container" createdb -U postgres -O odoo_app codestra_odoo_restore
docker exec "$container" createdb -U postgres -O middleware_app codestra_middleware
docker exec "$container" createdb -U postgres -O n8n_app codestra_n8n
docker exec "$container" createdb -U postgres -O keycloak keycloak

database_import_started_ns=$(date +%s%N)
for pair in odoo:codestra_odoo_restore middleware:codestra_middleware n8n:codestra_n8n keycloak:keycloak; do
    file=${pair%%:*}
    database=${pair#*:}
    docker cp "$work_dir/${file}.dump" "$container:/tmp/${file}.dump" >/dev/null
    restore_args=(--exit-on-error --no-owner)
    case "$database" in
        codestra_odoo_restore) restore_args+=(--role=odoo_app) ;;
        codestra_middleware) restore_args+=(--role=middleware_app) ;;
        codestra_n8n) restore_args+=(--role=n8n_app) ;;
        keycloak) restore_args+=(--role=keycloak) ;;
    esac
    docker exec "$container" pg_restore -U postgres -d "$database" \
        "${restore_args[@]}" "/tmp/${file}.dump" >/dev/null
done
database_import_finished_ns=$(date +%s%N)
database_import_ms=$(( (database_import_finished_ns - database_import_started_ns) / 1000000 ))

database_count=$(docker exec "$container" psql -U postgres -d postgres -Atc \
    "select count(*) from pg_database where datallowconn and not datistemplate")
test "$database_count" -ge 5
for identity in \
    odoo_app:codestra_odoo_restore \
    middleware_app:codestra_middleware \
    n8n_app:codestra_n8n \
    keycloak:keycloak; do
    role=${identity%%:*}
    database=${identity#*:}
    object_count=$(docker exec "$container" psql -U "$role" -d "$database" -Atc \
        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where c.relkind in ('r','p','v','m') and n.nspname not in ('pg_catalog','information_schema') and n.nspname !~ '^pg_toast'")
    test "$object_count" -gt 0
done

restored_filestore="$work_dir/restored-volumes/odoo/.local/share/Odoo/filestore"
test -d "$restored_filestore/codestra_odoo"
test ! -e "$restored_filestore/codestra_odoo_restore"
mv "$restored_filestore/codestra_odoo" "$restored_filestore/codestra_odoo_restore"

missing_attachment_checksums=$(docker exec "$container" psql -U postgres -d codestra_odoo_restore -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM ir_attachment WHERE store_fname IS NOT NULL AND (checksum IS NULL OR btrim(checksum) = '')")
test "$missing_attachment_checksums" -eq 0
docker exec "$container" psql -U postgres -d codestra_odoo_restore -At -F '|' -v ON_ERROR_STOP=1 \
    -c "SELECT store_fname, checksum FROM ir_attachment WHERE store_fname IS NOT NULL ORDER BY store_fname" \
    > "$work_dir/restored-odoo-attachments.tsv"
cmp "$work_dir/odoo-attachments.tsv" "$work_dir/restored-odoo-attachments.tsv"
python3 "$validator" \
    --metadata "$work_dir/ODOO-BACKUP-METADATA" \
    --data-dir "$work_dir/restored-volumes/odoo" \
    --attachment-map "$work_dir/restored-odoo-attachments.tsv" \
    --backup-id "${backup_dir##*/}" \
    --restored-database codestra_odoo_restore \
    --output "$final_dir/ODOO-FILESTORE-VALIDATION.json" >/dev/null

odoo_authenticated_object_count=$(docker exec "$container" sh -ec \
    'PGPASSWORD=$(cat /run/secrets/rehearsal_db_password); export PGPASSWORD; psql -h postgres -U odoo_app -d codestra_odoo_restore -At -v ON_ERROR_STOP=1 -c "select count(*) from public.ir_attachment"')
[[ "$odoo_authenticated_object_count" =~ ^[0-9]+$ ]]

cat > "$work_dir/odoo-rehearsal.conf" <<'EOF'
[options]
db_host = postgres
db_port = 5432
db_user = odoo_app
db_name = codestra_odoo_restore
dbfilter = ^codestra_odoo_restore$
list_db = False
proxy_mode = False
http_port = 8069
workers = 0
max_cron_threads = 0
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons,/mnt/integration-addons,/mnt/call-center-addons
EOF
printf 'db_password = %s\n' "$(<"$rehearsal_password_file")" >> "$work_dir/odoo-rehearsal.conf"
chmod 0400 "$work_dir/odoo-rehearsal.conf"
chown 100:101 "$work_dir/odoo-rehearsal.conf"

odoo_image=$(awk '$1 == "codestra-odoo-1" {print $2}' "$work_dir/BACKUP-MANIFEST.tsv")
test -n "$odoo_image"
docker image inspect "$odoo_image" >/dev/null
application_health_started_ns=$(date +%s%N)
docker run -d --name "$odoo_container" --network "$network" \
    --user 100:101 \
    -v "$work_dir/restored-volumes/odoo:/var/lib/odoo" \
    -v "$work_dir/odoo-rehearsal.conf:/etc/odoo/odoo.conf:ro" \
    -v "$work_dir/restored-configuration/opt/codestra/odoo-addons:/mnt/extra-addons:ro" \
    -v "$work_dir/restored-configuration/opt/codestra/staging-sources/app-odoo-identity-timezone-57ab123cded2-r2/integration:/mnt/integration-addons:ro" \
    -v "$work_dir/restored-configuration/opt/codestra/staging-sources/app-odoo-identity-timezone-57ab123cded2-r2/call-center:/mnt/call-center-addons:ro" \
    --entrypoint odoo "$odoo_image" \
    --config=/etc/odoo/odoo.conf --no-database-list --max-cron-threads=0 --workers=0 >/dev/null

odoo_health=failed
for _ in $(seq 1 90); do
    if docker exec "$odoo_container" python3 -c \
        'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8069/web/health", timeout=2).status == 200' \
        >/dev/null 2>&1; then
        odoo_health=healthy
        break
    fi
    test "$(docker inspect -f '{{.State.Running}}' "$odoo_container")" = true
    sleep 2
done
test "$odoo_health" = healthy
test "$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$odoo_container")" = null
test "$(docker network inspect -f '{{.Internal}}' "$network")" = true
application_health_finished_ns=$(date +%s%N)
application_health_ms=$(( (application_health_finished_ns - application_health_started_ns) / 1000000 ))
measured_rto_ms=$(( (application_health_finished_ns - rehearsal_started_ns) / 1000000 ))

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
ODOO_DATABASE_FILESTORE_PAIR_GATE=PASS
ODOO_DATABASE_AUTHENTICATION_GATE=PASS
ODOO_ISOLATED_APPLICATION_HEALTH_GATE=PASS
REPOSITORY_MATERIALIZATION_MS=${repository_materialization_ms}
DATABASE_IMPORT_MS=${database_import_ms}
APPLICATION_HEALTH_MS=${application_health_ms}
MEASURED_RTO_MS=${measured_rto_ms}
CONFIGURATION_RESTORE_GATE=PASS
LOCAL_RUNTIME_IMAGE_ARCHIVE_GATE=PASS
EXACT_RUNTIME_IMAGE_ID_BINDING_GATE=PASS
DISPOSABLE_CLEANUP_REQUIRED=YES
EOF
(cd "$final_dir" && sha256sum RESTORE-RESULT.txt ODOO-FILESTORE-VALIDATION.json > SHA256SUMS && sha256sum -c SHA256SUMS)
printf '%s\n' "$final_dir"
