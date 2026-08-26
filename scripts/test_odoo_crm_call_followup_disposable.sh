#!/usr/bin/env bash
set -Eeuo pipefail

workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
run_id="${GITHUB_RUN_ID:-local}-$$"
network="codestra-call-followup-ci-${run_id}"
postgres_container="codestra-call-followup-pg-${run_id}"
postgres_volume="codestra_call_followup_pg_${run_id}"
database=call_followup_ci
database_user=odoo_test
database_password=disposable-ci-only
odoo_image='odoo@sha256:94a4f480b8039dc9ca2bca9e77e59f97d3311f66e2aad663cf2670be9c66d4ea'
postgres_image='postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94'

cleanup() {
    docker rm -f "$postgres_container" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker volume rm "$postgres_volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

network_args=(--internal)
if [[ -n "${ODOO_TEST_SUBNET:-}" ]]; then
    network_args+=(--subnet "$ODOO_TEST_SUBNET")
fi
docker network create "${network_args[@]}" "$network" >/dev/null
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
        "$@"
}

echo 'DISPOSABLE_INSTALL_TEST=START'
odoo -i codestra_crm_call_followup \
    --test-enable --test-tags /codestra_crm_call_followup
echo 'DISPOSABLE_INSTALL_TEST=PASS'

odoo -u codestra_crm_call_followup
module_state=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT state || ':' || latest_version FROM ir_module_module WHERE name='codestra_crm_call_followup'")
[[ "$module_state" == 'installed:19.0.1.1.0' ]]
echo "DISPOSABLE_UPGRADE_TEST=PASS state=$module_state"

printf '%s\n' \
    "module = env['ir.module.module'].search([('name', '=', 'codestra_crm_call_followup')], limit=1)" \
    "assert module.state == 'installed', module.state" \
    'module.button_immediate_uninstall()' \
    'env.cr.commit()' |
    docker run --rm -i --network "$network" \
        -e HOST=call-followup-postgres \
        -e PORT=5432 \
        -e "USER=$database_user" \
        -e "PASSWORD=$database_password" \
        -v "$workspace/odoo_addons:/mnt/extra-addons:ro" \
        "$odoo_image" odoo shell \
        -d "$database" \
        --db_host=call-followup-postgres \
        --db_user="$database_user" \
        --db_password="$database_password" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        --no-http --max-cron-threads=0 --log-level=warn

module_state=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT state FROM ir_module_module WHERE name='codestra_crm_call_followup'")
module_table_count=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT count(*) FROM pg_class WHERE relname='codestra_crm_call_followup'")
[[ "$module_state" == 'uninstalled' ]]
[[ "$module_table_count" == '0' ]]
echo "DISPOSABLE_UNINSTALL_TEST=PASS state=$module_state table_count=$module_table_count"
echo 'DISPOSABLE_DATABASE_CLEANUP=PASS'
