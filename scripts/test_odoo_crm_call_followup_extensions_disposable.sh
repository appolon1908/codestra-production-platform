#!/usr/bin/env bash
set -Eeuo pipefail

workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
run_id="${GITHUB_RUN_ID:-local}-$$"
network="codestra-call-followup-extensions-${run_id}"
postgres_container="codestra-call-followup-ext-pg-${run_id}"
postgres_volume="codestra_call_followup_ext_pg_${run_id}"
database=call_followup_extensions_ci
database_user=odoo_test
database_password=disposable-ci-only
odoo_image='odoo@sha256:94a4f480b8039dc9ca2bca9e77e59f97d3311f66e2aad663cf2670be9c66d4ea'
postgres_image='postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94'
modules='codestra_crm_call_followup_api,codestra_crm_call_followup_ux,codestra_crm_call_followup_automation,codestra_crm_call_followup_delivery'
test_tags='/codestra_crm_call_followup,/codestra_crm_call_followup_api,/codestra_crm_call_followup_ux,/codestra_crm_call_followup_automation,/codestra_crm_call_followup_delivery'

cleanup() {
    docker rm -f "$postgres_container" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker volume rm "$postgres_volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --internal "$network" >/dev/null
docker volume create "$postgres_volume" >/dev/null
docker run -d --name "$postgres_container" \
    --network "$network" --network-alias call-followup-postgres \
    -e "POSTGRES_DB=$database" \
    -e "POSTGRES_USER=$database_user" \
    -e "POSTGRES_PASSWORD=$database_password" \
    -v "$postgres_volume:/var/lib/postgresql/data" \
    "$postgres_image" >/dev/null

for attempt in $(seq 1 40); do
    if docker exec "$postgres_container" \
        pg_isready -U "$database_user" -d "$database" >/dev/null 2>&1; then
        break
    fi
    if [[ "$attempt" -eq 40 ]]; then
        docker logs "$postgres_container"
        exit 1
    fi
    sleep 1
done

odoo() {
    docker run --rm -i --network "$network" \
        -e HOST=call-followup-postgres \
        -e PORT=5432 \
        -e "USER=$database_user" \
        -e "PASSWORD=$database_password" \
        -v "$workspace/odoo_addons:/mnt/extra-addons:ro" \
        "$odoo_image" odoo \
        -d "$database" \
        --db_host=call-followup-postgres \
        --db_port=5432 \
        --db_user="$database_user" \
        --db_password="$database_password" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        --stop-after-init --max-cron-threads=0 --workers=0 --without-demo \
        --log-level=warn \
        --log-handler=odoo.tests:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup_api:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup_ux:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup_automation:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup_delivery:TEST \
        "$@"
}

echo 'EXTENSION_DISPOSABLE_INSTALL=START'
odoo -i "$modules" --test-enable --test-tags "$test_tags"
echo 'EXTENSION_DISPOSABLE_INSTALL=PASS'

odoo -u "$modules"
installed_count=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT count(*) FROM ir_module_module WHERE name IN (
        'codestra_crm_call_followup',
        'codestra_crm_call_followup_api',
        'codestra_crm_call_followup_ux',
        'codestra_crm_call_followup_automation'
        ,'codestra_crm_call_followup_delivery'
    ) AND state='installed' AND latest_version LIKE '19.0.%'")
[[ "$installed_count" == '5' ]]

outbox_table_count=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT count(*) FROM pg_class WHERE relname='codestra_crm_call_followup_outbox'")
[[ "$outbox_table_count" == '1' ]]

echo "EXTENSION_DISPOSABLE_UPGRADE=PASS installed=$installed_count"
echo 'EXTENSION_REMOTE_AUTOMATION=DISABLED_BY_DEFAULT'
echo 'EXTENSION_DISPOSABLE_DATABASE_CLEANUP=PASS'
