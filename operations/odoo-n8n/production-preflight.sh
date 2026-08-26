#!/usr/bin/env bash
set -euo pipefail

# Read-only Odoo+n8n production preflight. This script never creates, restarts,
# pauses, or recreates a container and never reads secret values.

pass=0
fail=0
pending=0

emit_pass() { printf 'PASS: %s\n' "$1"; pass=$((pass + 1)); }
emit_fail() { printf 'FAIL: %s\n' "$1"; fail=$((fail + 1)); }
emit_pending() { printf 'PENDING: %s\n' "$1"; pending=$((pending + 1)); }

container_running_healthy() {
    local name=$1 status health restarts
    if ! docker inspect "$name" >/dev/null 2>&1; then
        emit_fail "$name exists"
        return
    fi
    status=$(docker inspect -f '{{.State.Status}}' "$name")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$name")
    restarts=$(docker inspect -f '{{.RestartCount}}' "$name")
    if [[ $status == running && $health == healthy && $restarts -eq 0 ]]; then
        emit_pass "$name running, healthy, zero restarts"
    else
        emit_fail "$name status=$status health=$health restarts=$restarts"
    fi
}

private_ports() {
    local name=$1 bindings
    bindings=$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$name")
    if [[ $bindings == '{}' || $bindings == 'null' ]]; then
        emit_pass "$name has no published host ports"
    else
        emit_fail "$name has published host ports"
    fi
}

container_running_healthy codestra-postgres-1
container_running_healthy codestra-odoo-1
container_running_healthy codestra-n8n-1
container_running_healthy codestra-middleware-integration-api-1
private_ports codestra-postgres-1
private_ports codestra-odoo-1
private_ports codestra-n8n-1

pg() { docker exec -u postgres codestra-postgres-1 psql -X -A -t -v ON_ERROR_STOP=1 "$@"; }

for database in codestra_odoo codestra_n8n; do
    if [[ $(pg -d postgres -c "select count(*) from pg_database where datname='$database' and datallowconn") == 1 ]]; then
        emit_pass "$database exists and accepts connections"
    else
        emit_fail "$database missing or connection-disabled"
    fi
done

for identity in odoo_app:codestra_odoo n8n_app:codestra_n8n; do
    role=${identity%%:*}; database=${identity#*:}
    role_state=$(pg -d postgres -c "select rolcanlogin::text||'|'||rolsuper::text from pg_roles where rolname='$role'")
    object_count=$(pg -d "$database" -c \
        "set role $role; select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relkind in ('r','p','v','m') and n.nspname not in ('pg_catalog','information_schema') and n.nspname !~ '^pg_toast'")
    object_count=${object_count##*$'\n'}
    if [[ $role_state == 'true|false' && $object_count =~ ^[1-9][0-9]*$ ]]; then
        emit_pass "$role least-privilege connectivity to $database"
    else
        emit_fail "$role database connectivity or privilege contract"
    fi
done

module_pending=$(pg -d codestra_odoo -c "select count(*) from ir_module_module where state in ('to install','to upgrade','to remove')")
if [[ $module_pending -eq 0 ]]; then
    emit_pass 'Odoo has no pending module transitions'
else
    emit_fail "Odoo pending module transitions=$module_pending"
fi

n8n_tables=$(pg -d codestra_n8n -c "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relkind in ('r','p') and n.nspname='public'")
if [[ $n8n_tables =~ ^[1-9][0-9]*$ ]]; then
    emit_pass 'n8n schema is populated'
else
    emit_fail 'n8n schema is empty'
fi

for endpoint in \
    'https://crm.codestra.agency/|200' \
    'https://n8n.codestra.agency/|401,403'; do
    url=${endpoint%%|*}; expected=${endpoint#*|}
    code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$url" || true)
    if grep -Eq "^(${expected//,/|})$" <<<"$code"; then
        emit_pass "$url controlled HTTP $code"
    else
        emit_fail "$url unexpected HTTP $code"
    fi
done

for target in 'odoo.internal.codestra.agency:443' 'n8n.internal.codestra.agency:443' 'codestra-postgres-1:5432'; do
    host=${target%:*}; port=${target##*:}
    if docker exec codestra-middleware-integration-api-1 python -c \
        'import socket,sys; s=socket.create_connection((sys.argv[1],int(sys.argv[2])),5); s.close()' \
        "$host" "$port" >/dev/null 2>&1; then
        emit_pass "middleware TCP path to $target"
    else
        emit_fail "middleware TCP path to $target"
    fi
done

archive_mode=$(pg -d postgres -c 'show archive_mode')
if [[ $archive_mode == on ]]; then
    emit_pass 'shared PostgreSQL WAL archiving active'
else
    emit_pending "shared PostgreSQL WAL archiving is $archive_mode until approved window"
fi

if [[ -r /etc/codestra/secrets/shared-postgresql/approved-change.env ]]; then
    validator=$(dirname "$0")/../shared-postgresql/validate-change-authority.sh
    authority_output=$(bash "$validator" /etc/codestra/secrets/shared-postgresql/approved-change.env 2>&1 || true)
    if grep -qx 'SHARED_POSTGRES_CUTOVER_GO=YES' <<<"$authority_output"; then
        emit_pass 'shared PostgreSQL cutover authority is GO'
    else
        blocker=$(awk -F= '$1=="BLOCKED_BY" {print $2}' <<<"$authority_output")
        emit_pending "shared PostgreSQL cutover authority: ${blocker:-not ready}"
    fi
else
    emit_fail 'protected shared PostgreSQL authority file is readable by root'
fi

used_percent=$(df --output=pcent /var/lib/docker | tail -n1 | tr -dc '0-9')
if [[ $used_percent -lt 80 ]]; then
    emit_pass "host storage used=${used_percent}%"
else
    emit_fail "host storage used=${used_percent}% (must be <80%)"
fi

printf '\nODOO_N8N_PREFLIGHT_PASS=%d\nODOO_N8N_PREFLIGHT_PENDING=%d\nODOO_N8N_PREFLIGHT_FAIL=%d\n' "$pass" "$pending" "$fail"
if (( fail > 0 )); then
    printf 'ODOO_N8N_READY_FOR_CHANGE_WINDOW=NO\n'
    exit 1
fi
printf 'ODOO_N8N_READY_FOR_CHANGE_WINDOW=YES\n'
