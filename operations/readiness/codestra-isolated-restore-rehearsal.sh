#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=/opt/codestra/backups/production-readiness-local
evidence_root=/opt/codestra/evidence/production-readiness-restore
release_config=/etc/codestra/production-operator/release.json
middleware_repository=ghcr.io/appolon1908-hue/codestra-middleware
middleware_source_sha=63b6c0c8bca5168a1178895bd12858d0b1e8086e
middleware_required_head=0056_klyrow_delivery_events
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work_dir="${evidence_root}/.work-${stamp}"
final_dir="${evidence_root}/${stamp}"
suffix=$(printf '%s' "$stamp" | tr -cd '0-9A-Za-z')
container="codestra-readiness-restore-${suffix}"
odoo_container="codestra-readiness-restore-odoo-${suffix}"
middleware_migrate_container="codestra-readiness-restore-middleware-migrate-${suffix}"
middleware_current_container="codestra-readiness-restore-middleware-current-${suffix}"
middleware_candidate_container="codestra-readiness-restore-middleware-candidate-${suffix}"
network="codestra-readiness-restore-${suffix}"
volume="codestra_readiness_restore_${suffix}"
rehearsal_started_ns=$(date +%s%N)
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
validator=
odoo_read_verifier=
for candidate in \
    "$script_dir/../restore/validate_odoo_filestore_pair.py" \
    "$script_dir/../../restore/validate_odoo_filestore_pair.py" \
    /opt/codestra/operations/restore/validate_odoo_filestore_pair.py; do
    if [[ -f "$candidate" && -r "$candidate" ]]; then
        validator=$candidate
        break
    fi
done
for candidate in \
    "$script_dir/../restore/verify_odoo_filestore_reads.py" \
    "$script_dir/../../restore/verify_odoo_filestore_reads.py" \
    /opt/codestra/operations/restore/verify_odoo_filestore_reads.py; do
    if [[ -f "$candidate" && -r "$candidate" ]]; then
        odoo_read_verifier=$candidate
        break
    fi
done

cleanup() {
    docker rm -f "$middleware_candidate_container" >/dev/null 2>&1 || true
    docker rm -f "$middleware_current_container" >/dev/null 2>&1 || true
    docker rm -f "$middleware_migrate_container" >/dev/null 2>&1 || true
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
trap 'exit 130' INT
trap 'exit 143' TERM
on_error() {
    local rc=$?
    printf 'RESTORE_REHEARSAL_GATE=FAIL\nRESTORE_FAIL_LINE=%s\nRESTORE_FAIL_RC=%s\n' "${BASH_LINENO[0]}" "$rc" >&2
    printf 'RESTORE_REHEARSAL_GATE=FAIL\nRESTORE_FAIL_LINE=%s\nRESTORE_FAIL_RC=%s\n' "${BASH_LINENO[0]}" "$rc" > "$final_dir/FAILURE.txt"
    for error_log in "$work_dir"/pg-restore-*.stderr; do
        [[ -f "$error_log" ]] || continue
        printf 'RESTORE_ERROR_LOG=%s\n' "${error_log##*/}" >&2
        sed -n '1,120p' "$error_log" >&2
        cp "$error_log" "$final_dir/${error_log##*/}"
    done
    for diagnostic in "$work_dir"/expected-*-owners.txt "$work_dir"/restored-*-owners.txt "$work_dir"/*default-acl.txt; do
        [[ -f "$diagnostic" ]] && cp "$diagnostic" "$final_dir/${diagnostic##*/}"
    done
}
trap on_error ERR

mkdir -p "$work_dir" "$final_dir"
chmod 0700 "$work_dir" "$final_dir"

backup_stamp=$(python3 - "$backup_root/LAST_SUCCESS" <<'PY'
import os
import re
import stat
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
with os.fdopen(descriptor, "rb") as stream:
    info = os.fstat(stream.fileno())
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SystemExit("unsafe readiness backup marker")
    value = stream.read().decode("ascii").strip()
if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", value) is None:
    raise SystemExit("malformed readiness backup marker")
print(value)
PY
)
backup_dir="${backup_root}/${backup_stamp}"
test ! -L "$backup_dir"
test "$(stat -c '%U:%G:%a' "$backup_dir")" = root:root:700
grep -qx 'BACKUP_STATUS=PASS' "$backup_dir/STATUS.txt"
encrypted="${backup_dir}/codestra-${backup_stamp}.tar.gz.gpg"
test -f "$encrypted"
test ! -L "$encrypted"

mapfile -t release_values < <(python3 - "$release_config" <<'PY'
import json
import os
import re
import stat
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
with os.fdopen(descriptor, "rb") as stream:
    info = os.fstat(stream.fileno())
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise SystemExit("unsafe production release tuple")
    value = json.load(stream)
if set(value) != {"protected_sha", "image_digest", "change_id", "maintenance_date"}:
    raise SystemExit("production release tuple schema mismatch")
if re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("image_digest", "")) is None:
    raise SystemExit("production release image digest malformed")
print(value["image_digest"])
PY
)
test "${#release_values[@]}" -eq 1
middleware_image="${middleware_repository}@${release_values[0]}"
docker image inspect "$middleware_image" >/dev/null
docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$middleware_image" \
    | grep -Fx "$middleware_image" >/dev/null
test "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$middleware_image")" = "$middleware_source_sha"

# Read-only production baselines prove the rehearsal cannot alter live roles.
docker exec codestra-postgres-1 psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 \
    -c "select r.rolname||'|'||r.rolcanlogin||'|'||r.rolsuper||'|'||r.rolinherit||'|'||r.rolbypassrls from pg_roles r where r.rolname in ('middleware_app','middleware_data_owner','mw_integration_api') order by 1; select mr.rolname||'->'||gr.rolname from pg_auth_members am join pg_roles mr on mr.oid=am.member join pg_roles gr on gr.oid=am.roleid where mr.rolname in ('middleware_app','mw_integration_api') order by 1; select 'mw_integration_api|public|CREATE|'||has_schema_privilege('mw_integration_api','public','CREATE')||'|USAGE|'||has_schema_privilege('mw_integration_api','public','USAGE')" \
    > "$work_dir/production-middleware-role-baseline.txt"
grep -qx 'middleware_data_owner|false|false|true|false' "$work_dir/production-middleware-role-baseline.txt"
grep -qx 'mw_integration_api|true|false|false|false' "$work_dir/production-middleware-role-baseline.txt"
production_membership_count=$(grep -c '^middleware_app->middleware_data_owner$' "$work_dir/production-middleware-role-baseline.txt" || true)
test "$production_membership_count" -eq 0
test "$(grep -c '^mw_integration_api->' "$work_dir/production-middleware-role-baseline.txt" || true)" -eq 0
docker exec codestra-identity-identity-db-1 psql -U keycloak -d keycloak -At -v ON_ERROR_STOP=1 \
    -c "select r.rolname||'|'||r.rolcanlogin||'|'||r.rolsuper||'|'||r.rolinherit from pg_roles r where r.rolname in ('keycloak','keycloak_data_owner') order by 1; select mr.rolname||'->'||gr.rolname from pg_auth_members am join pg_roles mr on mr.oid=am.member join pg_roles gr on gr.oid=am.roleid where mr.rolname='keycloak' order by 1" \
    > "$work_dir/production-keycloak-role-baseline.txt"
grep -qx 'keycloak_data_owner|false|false|true' "$work_dir/production-keycloak-role-baseline.txt"
test "$(grep -c '^keycloak->keycloak_data_owner$' "$work_dir/production-keycloak-role-baseline.txt" || true)" -eq 0
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
test -n "$odoo_read_verifier"
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
CREATE ROLE keycloak_data_owner;
CREATE ROLE codestra_monitoring;
CREATE ROLE middleware_app LOGIN;
CREATE ROLE middleware_data_owner;
CREATE ROLE mw_event_gateway;
CREATE ROLE mw_evidence_runner;
CREATE ROLE mw_extension_allocator;
CREATE ROLE mw_integration_api LOGIN NOINHERIT PASSWORD :'rehearsal_password';
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
test "$(docker exec "$container" psql -U postgres -d postgres -Atc "select rolcanlogin from pg_roles where rolname='middleware_data_owner'")" = f
test "$(docker exec "$container" psql -U postgres -d postgres -Atc "select rolcanlogin from pg_roles where rolname='keycloak_data_owner'")" = f
test "$(docker exec "$container" psql -U postgres -d postgres -Atc "select pg_has_role('middleware_app','middleware_data_owner','MEMBER')")" = f
test "$(docker exec "$container" psql -U postgres -d postgres -Atc "select pg_has_role('keycloak','keycloak_data_owner','MEMBER')")" = f
test "$(docker exec "$container" psql -U postgres -d postgres -Atc "select rolcanlogin||'|'||rolsuper||'|'||rolbypassrls from pg_roles where rolname='mw_integration_api'")" = 'true|false|false'
docker exec "$container" createdb -U postgres -O odoo_app codestra_odoo_restore
docker exec "$container" createdb -U postgres -O middleware_data_owner codestra_middleware
docker exec "$container" createdb -U postgres -O n8n_app codestra_n8n
docker exec "$container" createdb -U postgres -O keycloak_data_owner keycloak

database_import_started_ns=$(date +%s%N)
for pair in odoo:codestra_odoo_restore middleware:codestra_middleware n8n:codestra_n8n keycloak:keycloak; do
    file=${pair%%:*}
    database=${pair#*:}
    docker cp "$work_dir/${file}.dump" "$container:/tmp/${file}.dump" >/dev/null
    # Run as the disposable cluster superuser and retain archive ownership.
    # All required roles and the isolated membership graph exist before this.
    restore_args=(--exit-on-error)
    docker exec "$container" pg_restore -U postgres -d "$database" \
        "${restore_args[@]}" "/tmp/${file}.dump" \
        >"$work_dir/pg-restore-${file}.stdout" 2>"$work_dir/pg-restore-${file}.stderr"
done
pg_restore_errors=$(awk 'BEGIN { IGNORECASE=1 } /(^|[[:space:]])error:/ { count++ } END { print count + 0 }' "$work_dir"/pg-restore-*.stderr)
test "$pg_restore_errors" -eq 0
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

ownership_sql="select n.nspname||'.'||c.relname||'|'||c.relkind::text||'|'||r.rolname from pg_class c join pg_namespace n on n.oid=c.relnamespace join pg_roles r on r.oid=c.relowner where n.nspname not in ('pg_catalog','information_schema') and n.nspname !~ '^pg_toast' order by 1"
default_acl_sql="select defaclrole::regrole::text||'|'||coalesce(defaclnamespace::regnamespace::text,'')||'|'||defaclobjtype::text||'|'||defaclacl::text from pg_default_acl order by 1"
reassigned_ownership_mismatches=0
for mapping in expected-codestra_odoo-owners.txt:codestra_odoo_restore expected-codestra_middleware-owners.txt:codestra_middleware expected-codestra_n8n-owners.txt:codestra_n8n; do
    source_database=${mapping%%:*}
    restored_database=${mapping#*:}
    restored_file="restored-${source_database#expected-}"
    docker exec "$container" psql -U postgres -d "$restored_database" -At -v ON_ERROR_STOP=1 -c "$ownership_sql" > "$work_dir/$restored_file"
    if ! cmp -s "$work_dir/$source_database" "$work_dir/$restored_file"; then
        reassigned_ownership_mismatches=$((reassigned_ownership_mismatches + 1))
    fi
done
docker exec "$container" psql -U postgres -d keycloak -At -v ON_ERROR_STOP=1 -c "$ownership_sql" > "$work_dir/restored-keycloak-owners.txt"
if ! cmp -s "$work_dir/expected-keycloak-owners.txt" "$work_dir/restored-keycloak-owners.txt"; then
    reassigned_ownership_mismatches=$((reassigned_ownership_mismatches + 1))
fi
test "$reassigned_ownership_mismatches" -eq 0
docker exec "$container" psql -U postgres -d codestra_middleware -At -v ON_ERROR_STOP=1 -c "$default_acl_sql" > "$work_dir/restored-default-acl.txt"
default_acl_mismatches=0
cmp -s "$work_dir/expected-default-acl.txt" "$work_dir/restored-default-acl.txt" || default_acl_mismatches=1
test "$default_acl_mismatches" -eq 0
docker exec "$container" psql -U postgres -d codestra_middleware -At -v ON_ERROR_STOP=1 \
    -c "select r.rolname||'|'||r.rolcanlogin||'|'||r.rolsuper||'|'||r.rolinherit||'|'||r.rolbypassrls from pg_roles r where r.rolname in ('middleware_app','middleware_data_owner','mw_integration_api') order by 1; select mr.rolname||'->'||gr.rolname from pg_auth_members am join pg_roles mr on mr.oid=am.member join pg_roles gr on gr.oid=am.roleid where mr.rolname in ('middleware_app','mw_integration_api') order by 1; select 'mw_integration_api|public|CREATE|'||has_schema_privilege('mw_integration_api','public','CREATE')||'|USAGE|'||has_schema_privilege('mw_integration_api','public','USAGE')" \
    > "$work_dir/restored-middleware-migration-role.txt"
cmp "$work_dir/production-middleware-role-baseline.txt" "$work_dir/restored-middleware-migration-role.txt"

# Prove that the exact staged candidate can migrate the restored Middleware
# database to the release head before production is touched.  The credential is
# disposable and mounted as a file, never placed in image metadata or evidence.
middleware_database_url_file="$work_dir/middleware-database-url"
printf 'postgresql+asyncpg://mw_integration_api:%s@postgres:5432/codestra_middleware\n' \
    "$(<"$rehearsal_password_file")" > "$middleware_database_url_file"
chmod 0444 "$middleware_database_url_file"
middleware_container_args=(
    --network "$network"
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges
    --tmpfs /tmp:rw,noexec,nosuid,size=32m,uid=10001,gid=10001
    -e DATABASE_URL_FILE=/run/secrets/database_url
    -e ENVIRONMENT=test
    -v "$middleware_database_url_file:/run/secrets/database_url:ro"
)
docker run --rm --name "$middleware_migrate_container" \
    "${middleware_container_args[@]}" "$middleware_image" \
    -m alembic upgrade head > "$work_dir/middleware-alembic-upgrade.txt"
docker run --rm --name "$middleware_current_container" \
    "${middleware_container_args[@]}" "$middleware_image" \
    -m alembic current > "$work_dir/middleware-alembic-current.txt"
middleware_database_head=$(awk 'NF {value=$1} END {print value}' "$work_dir/middleware-alembic-current.txt")
test "$middleware_database_head" = "$middleware_required_head"
middleware_schema_table_count=$(docker exec "$container" psql -U postgres -d codestra_middleware -At -v ON_ERROR_STOP=1 \
    -c "select count(*) from information_schema.tables where table_schema='public' and table_name in ('klyrow_delivery_event_inbox','klyrow_delivery_analytics')")
test "$middleware_schema_table_count" -eq 2

middleware_secret_file="$work_dir/middleware-secret"
quarantine_encryption_file="$work_dir/quarantine-encryption-key"
quarantine_fingerprint_file="$work_dir/quarantine-fingerprint-key"
quarantine_reviewer_file="$work_dir/quarantine-reviewer-key"
openssl rand -hex 32 > "$middleware_secret_file"
for secret_file in \
    "$quarantine_encryption_file" \
    "$quarantine_fingerprint_file" \
    "$quarantine_reviewer_file"; do
    openssl rand -base64 32 | tr -d '\n' > "$secret_file"
    printf '\n' >> "$secret_file"
done
chmod 0444 \
    "$middleware_secret_file" \
    "$quarantine_encryption_file" \
    "$quarantine_fingerprint_file" \
    "$quarantine_reviewer_file"
docker run -d --name "$middleware_candidate_container" \
    "${middleware_container_args[@]}" \
    --network-alias middleware-candidate \
    -e PORT=8095 \
    -e SERVICE_NAME=middleware-integration-api \
    -e HEALTH_REQUIRE_DATABASE=true \
    -e MIDDLEWARE_SECRET_FILE=/run/secrets/middleware_secret \
    -e QUARANTINE_ENCRYPTION_KEY_FILE=/run/secrets/quarantine_encryption_key \
    -e QUARANTINE_FINGERPRINT_SECRET_FILE=/run/secrets/quarantine_fingerprint_key \
    -e QUARANTINE_REVIEWER_SECRET_FILE=/run/secrets/quarantine_reviewer_key \
    -v "$middleware_secret_file:/run/secrets/middleware_secret:ro" \
    -v "$quarantine_encryption_file:/run/secrets/quarantine_encryption_key:ro" \
    -v "$quarantine_fingerprint_file:/run/secrets/quarantine_fingerprint_key:ro" \
    -v "$quarantine_reviewer_file:/run/secrets/quarantine_reviewer_key:ro" \
    "$middleware_image" -m app.entrypoints.integration_api >/dev/null
middleware_candidate_health=failed
for _ in $(seq 1 90); do
    if docker run --rm --network "$network" "$middleware_image" -c \
        'import json,urllib.request; health=json.load(urllib.request.urlopen("http://middleware-candidate:8095/healthz",timeout=2)); ready=json.load(urllib.request.urlopen("http://middleware-candidate:8095/readyz",timeout=2)); assert health["status"]=="ok"; assert ready["status"]=="ready" and ready["database"]=="online" and ready["delivery"]=="disabled"' \
        >/dev/null 2>&1; then
        middleware_candidate_health=healthy
        break
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$middleware_candidate_container")" != true ]]; then
        docker logs "$middleware_candidate_container" > "$final_dir/MIDDLEWARE-CANDIDATE-STARTUP.log" 2>&1 || true
        echo "MIDDLEWARE_CANDIDATE_START=FAIL" >&2
        exit 1
    fi
    sleep 2
done
test "$middleware_candidate_health" = healthy
middleware_candidate_port_bindings=$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$middleware_candidate_container")
[[ "$middleware_candidate_port_bindings" == null || "$middleware_candidate_port_bindings" == '{}' ]]

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
    if [[ "$(docker inspect -f '{{.State.Running}}' "$odoo_container")" != true ]]; then
        docker logs "$odoo_container" > "$final_dir/ODOO-STARTUP.log" 2>&1 || true
        echo "ODOO_START=FAIL" >&2
        exit 1
    fi
    sleep 2
done
test "$odoo_health" = healthy
port_bindings=$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$odoo_container")
[[ "$port_bindings" == null || "$port_bindings" == '{}' ]]
test "$(docker network inspect -f '{{.Internal}}' "$network")" = true

# A healthy process and host-side hashes do not prove that Odoo can resolve the
# restored database-keyed filestore.  Exercise every filestore-backed attachment
# through ir.attachment and compare the bytes Odoo returns with its DB checksum.
docker cp "$odoo_read_verifier" "$odoo_container:/tmp/verify_odoo_filestore_reads.py" >/dev/null
docker exec -i "$odoo_container" odoo shell \
    --config=/etc/odoo/odoo.conf --no-http --no-database-list \
    > "$work_dir/odoo-filestore-read-result.txt" <<'PY'
exec(compile(open("/tmp/verify_odoo_filestore_reads.py", "rb").read(), "/tmp/verify_odoo_filestore_reads.py", "exec"))
run(env)
PY
grep -q '^ODOO_FILESTORE_READ_RESULT=' "$work_dir/odoo-filestore-read-result.txt"
odoo_filestore_objects_read=$(python3 - "$work_dir/odoo-filestore-read-result.txt" <<'PY'
import json
import sys

prefix = "ODOO_FILESTORE_READ_RESULT="
lines = [line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.startswith(prefix)]
if len(lines) != 1:
    raise SystemExit("expected exactly one Odoo filestore read result")
result = json.loads(lines[0][len(prefix):])
if result.get("read_failures") != 0 or result.get("odoo_filestore_objects_read", 0) < 2:
    raise SystemExit("Odoo filestore read verification failed")
print(result["odoo_filestore_objects_read"])
PY
)
application_health_finished_ns=$(date +%s%N)
application_health_ms=$(( (application_health_finished_ns - application_health_started_ns) / 1000000 ))
measured_rto_ms=$(( (application_health_finished_ns - rehearsal_started_ns) / 1000000 ))

docker exec codestra-postgres-1 psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 \
    -c "select r.rolname||'|'||r.rolcanlogin||'|'||r.rolsuper||'|'||r.rolinherit||'|'||r.rolbypassrls from pg_roles r where r.rolname in ('middleware_app','middleware_data_owner','mw_integration_api') order by 1; select mr.rolname||'->'||gr.rolname from pg_auth_members am join pg_roles mr on mr.oid=am.member join pg_roles gr on gr.oid=am.roleid where mr.rolname in ('middleware_app','mw_integration_api') order by 1; select 'mw_integration_api|public|CREATE|'||has_schema_privilege('mw_integration_api','public','CREATE')||'|USAGE|'||has_schema_privilege('mw_integration_api','public','USAGE')" \
    > "$work_dir/production-middleware-role-after.txt"
docker exec codestra-identity-identity-db-1 psql -U keycloak -d keycloak -At -v ON_ERROR_STOP=1 \
    -c "select r.rolname||'|'||r.rolcanlogin||'|'||r.rolsuper||'|'||r.rolinherit from pg_roles r where r.rolname in ('keycloak','keycloak_data_owner') order by 1; select mr.rolname||'->'||gr.rolname from pg_auth_members am join pg_roles mr on mr.oid=am.member join pg_roles gr on gr.oid=am.roleid where mr.rolname='keycloak' order by 1" \
    > "$work_dir/production-keycloak-role-after.txt"
cmp "$work_dir/production-middleware-role-baseline.txt" "$work_dir/production-middleware-role-after.txt"
cmp "$work_dir/production-keycloak-role-baseline.txt" "$work_dir/production-keycloak-role-after.txt"
cp "$work_dir/production-middleware-role-baseline.txt" "$final_dir/PRODUCTION-MIDDLEWARE-ROLE-BASELINE.txt"
cp "$work_dir/production-middleware-role-after.txt" "$final_dir/PRODUCTION-MIDDLEWARE-ROLE-AFTER.txt"
cp "$work_dir/restored-middleware-migration-role.txt" "$final_dir/RESTORED-MIDDLEWARE-MIGRATION-ROLE.txt"
cp "$work_dir/production-keycloak-role-baseline.txt" "$final_dir/PRODUCTION-KEYCLOAK-ROLE-BASELINE.txt"
cp "$work_dir/production-keycloak-role-after.txt" "$final_dir/PRODUCTION-KEYCLOAK-ROLE-AFTER.txt"

cat > "$final_dir/RESTORE-RESULT.txt" <<EOF
RESTORE_REHEARSAL_GATE=PASS
RESTORE_BACKUP_STAMP=${backup_stamp}
ISOLATED_ROLE_MODEL=PASS
MIDDLEWARE_DATA_OWNER_NOLOGIN=PASS
KEYCLOAK_DATA_OWNER_NOLOGIN=PASS
RESTORE_ROLE_MEMBERSHIP_SCOPE=ISOLATED_ONLY
PRODUCTION_ROLE_PRIVILEGES_UNCHANGED=PASS
PG_RESTORE=PASS
PG_RESTORE_ERRORS=${pg_restore_errors}
DEFAULT_PRIVILEGES_RESTORED=PASS
DEFAULT_ACL_MISMATCHES=${default_acl_mismatches}
OBJECT_OWNERSHIP=PASS
REASSIGNED_OWNERSHIP_MISMATCHES=${reassigned_ownership_mismatches}
DATABASE_RESTORE=PASS
FILESTORE_RESTORE=PASS
ODOO_ORM_FILESTORE_READS=PASS
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
ODOO_FILESTORE_OBJECT_READ_GATE=PASS
ODOO_FILESTORE_OBJECTS_READ=${odoo_filestore_objects_read}
REPOSITORY_MATERIALIZATION_MS=${repository_materialization_ms}
DATABASE_IMPORT_MS=${database_import_ms}
APPLICATION_HEALTH_MS=${application_health_ms}
MEASURED_RTO_MS=${measured_rto_ms}
CONFIGURATION_RESTORE_GATE=PASS
LOCAL_RUNTIME_IMAGE_ARCHIVE_GATE=PASS
EXACT_RUNTIME_IMAGE_ID_BINDING_GATE=PASS
MIDDLEWARE_CANDIDATE_IMAGE=${middleware_image}
MIDDLEWARE_CANDIDATE_SOURCE_SHA=${middleware_source_sha}
MIDDLEWARE_MIGRATION_HEAD=${middleware_database_head}
MIDDLEWARE_SCHEMA_TABLE_COUNT=${middleware_schema_table_count}
MIDDLEWARE_ISOLATED_MIGRATION_GATE=PASS
MIDDLEWARE_MIGRATION_IDENTITY=mw_integration_api
MIDDLEWARE_PRODUCTION_GRANTS_MATCH=PASS
MIDDLEWARE_CANDIDATE_HEALTH_GATE=PASS
MIDDLEWARE_CANDIDATE_READINESS_GATE=PASS
MIDDLEWARE_CANDIDATE_DATABASE_READINESS=PASS
DISPOSABLE_CLEANUP_REQUIRED=YES
EOF
(cd "$final_dir" && sha256sum RESTORE-RESULT.txt ODOO-FILESTORE-VALIDATION.json PRODUCTION-*-ROLE-*.txt RESTORED-MIDDLEWARE-MIGRATION-ROLE.txt > SHA256SUMS && sha256sum -c SHA256SUMS)
printf '%s\n' "$stamp" > "$evidence_root/.LAST_SUCCESS-${stamp}"
chmod 0600 "$evidence_root/.LAST_SUCCESS-${stamp}"
sync "$evidence_root/.LAST_SUCCESS-${stamp}"
mv "$evidence_root/.LAST_SUCCESS-${stamp}" "$evidence_root/LAST_SUCCESS"
sync -d "$evidence_root"
printf '%s\n' "$final_dir"
