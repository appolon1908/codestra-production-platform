#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

COMPOSE=/opt/codestra/compose/compose.yaml
ODOO_CONTAINER=codestra-odoo-1
POSTGRES_CONTAINER=codestra-postgres-1
ODOO_VOLUME=codestra_odoo_data
DATABASE=codestra_odoo
ADDONS=/opt/codestra/odoo-addons
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST=${1:-/root/odoo19-representative-migration-$STAMP/source-pair}
START_EPOCH=$(date +%s)
ODOO_STOPPED=0

mkdir -p "$DEST"
chmod 0700 "$DEST"

restart_odoo() {
    if [[ "$ODOO_STOPPED" == 1 ]]; then
        docker start "$ODOO_CONTAINER" >/dev/null
        for _ in $(seq 1 120); do
            status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$ODOO_CONTAINER")
            [[ "$status" == healthy ]] && break
            sleep 1
        done
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$ODOO_CONTAINER")
        [[ "$status" == healthy ]]
        ODOO_STOPPED=0
    fi
}
trap restart_odoo EXIT

[[ $(docker inspect -f '{{.Name}}' "$ODOO_CONTAINER") == "/$ODOO_CONTAINER" ]]
[[ $(docker inspect -f '{{.Name}}' "$POSTGRES_CONTAINER") == "/$POSTGRES_CONTAINER" ]]
docker volume inspect "$ODOO_VOLUME" >/dev/null

docker compose -f "$COMPOSE" exec -T postgres psql -U postgres -d "$DATABASE" -At >"$DEST/fail-closed.before" <<'SQL'
SELECT key || '=' || lower(value)
FROM ir_config_parameter
WHERE lower(key) IN (
  'send_events', 'production_callbacks_enabled', 'vicidial_writes_enabled',
  'external_dial_enabled', 'n8n_production_workflows_enabled'
)
ORDER BY key;
SQL
awk -F= '/^(SEND_EVENTS|LIVE_WRITES_ENABLED|ODOO_WRITE_ENABLED|N8N_DELIVERY_ENABLED)=/ {
    print $1 "=" tolower($2)
}' /opt/codestra/env/middleware.env >"$DEST/runtime-fail-closed.before"
for key in SEND_EVENTS LIVE_WRITES_ENABLED ODOO_WRITE_ENABLED N8N_DELIVERY_ENABLED; do
    grep -qx "$key=false" "$DEST/runtime-fail-closed.before"
done
if [[ -s "$DEST/fail-closed.before" ]]; then
    awk -F= 'tolower($2) == "false" {next} {exit 1}' "$DEST/fail-closed.before"
fi

docker inspect -f \
    'name={{.Name}} image={{.Image}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} started={{.State.StartedAt}} networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}},{{end}} mounts={{range .Mounts}}{{.Type}}:{{.Name}}:{{.Destination}},{{end}}' \
    "$ODOO_CONTAINER" "$POSTGRES_CONTAINER" >"$DEST/containers.before.txt"
git -C "$ADDONS" rev-parse HEAD >"$DEST/addons.commit"
git -C "$ADDONS" status --short --branch >"$DEST/addons.status"
find "$ADDONS" -type f -not -path "$ADDONS/.git/*" -print0 |
    sort -z | xargs -0 sha256sum >"$DEST/addons-files.sha256"

WINDOW_START=$(date -u +%FT%TZ)
docker stop --time 45 "$ODOO_CONTAINER" >"$DEST/odoo.stop"
ODOO_STOPPED=1

connections=$(docker exec "$POSTGRES_CONTAINER" psql -U postgres -d postgres -Atc \
    "select count(*) from pg_stat_activity where datname='$DATABASE' and pid <> pg_backend_pid()")
[[ "$connections" == 0 ]]
printf 'APPLICATION_CONNECTIONS_AFTER_QUIESCE=%s\n' "$connections" >"$DEST/consistency-window.env"

docker exec "$POSTGRES_CONTAINER" pg_dump -U postgres -Fc --serializable-deferrable "$DATABASE" \
    >"$DEST/codestra_odoo.pre19.dump"
docker run --rm -v "$ODOO_VOLUME:/source:ro" -v "$DEST:/backup" alpine:3.22 \
    tar -C /source -czf /backup/odoo-filestore.tar.gz \
    .local/share/Odoo/filestore/codestra_odoo

docker run --rm -v "$DEST:/backup:ro" postgres:17.6-alpine \
    pg_restore --list /backup/codestra_odoo.pre19.dump >"$DEST/dump.catalog"
tar -tzf "$DEST/odoo-filestore.tar.gz" |
    sed -n '/\/$/!p' |
    LC_ALL=C sort >"$DEST/filestore.files"

WINDOW_END=$(date -u +%FT%TZ)
restart_odoo

docker compose -f "$COMPOSE" exec -T postgres psql -U postgres -d "$DATABASE" -At -F '|' >"$DEST/database-profile.txt" <<'SQL'
SELECT current_database(), current_setting('server_version'), pg_database_size(current_database());
SELECT count(*) AS tables FROM pg_tables WHERE schemaname='public';
SELECT count(*) AS modules FROM ir_module_module;
SELECT count(*) AS users FROM res_users;
SELECT count(*) AS attachments FROM ir_attachment;
SELECT count(*) AS stored_attachments FROM ir_attachment WHERE store_fname IS NOT NULL;
SELECT name, latest_version, state FROM ir_module_module
WHERE state='installed' AND name LIKE 'codestra_%' ORDER BY name;
SQL

cat >>"$DEST/consistency-window.env" <<EOF
CONSISTENCY_WINDOW_START_UTC=$WINDOW_START
CONSISTENCY_WINDOW_END_UTC=$WINDOW_END
ODOO_QUIESCED_DURING_DATABASE_AND_FILESTORE_CAPTURE=true
DATABASE_DUMP_FORMAT=postgresql_custom
DATABASE_DUMP_SERIALIZABLE_DEFERRABLE=true
ODOO_POST_CAPTURE_HEALTH=healthy
CAPTURE_SECONDS=$(($(date +%s) - START_EPOCH))
EOF

find "$DEST" -maxdepth 1 -type f ! -name SHA256SUMS -print0 |
    sort -z | xargs -0 sha256sum >"$DEST/SHA256SUMS"
chmod 0600 "$DEST"/*
sha256sum -c "$DEST/SHA256SUMS"
printf 'SOURCE_PAIR=%s\n' "$DEST"
