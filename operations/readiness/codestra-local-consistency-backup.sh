#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=/opt/codestra/backups/production-readiness-local
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work_dir="${backup_root}/.work-${stamp}"
final_dir="${backup_root}/${stamp}"
paused=()

validate_owner_window_waiver() {
    /usr/bin/python3 - <<'PY'
import hashlib
import os
import re
import stat

waiver_root = "/opt/codestra/evidence/production-readiness-soak/20260822T022734Z"
waiver_path = f"{waiver_root}/OWNER-MAINTENANCE-WINDOW-WAIVER.txt"
checksum_path = f"{waiver_root}/OWNER-MAINTENANCE-WINDOW-WAIVER.sha256"
required = {
    "MAINTENANCE_WINDOW=WAIVED_BY_OWNER",
    "MAINTENANCE_WINDOW_WAIVER_APPROVED=YES",
    "MAINTENANCE_WINDOW_WAIVER_AUTHORITY=OWNER",
    "IMMEDIATE_PRODUCTION_MUTATION_AUTHORIZED=YES",
}


def read_root_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("unsafe file type")
        if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("unsafe ownership or mode")
        return stream.read()


try:
    waiver = read_root_file(waiver_path)
    checksum = read_root_file(checksum_path).decode("ascii").strip()
    match = re.fullmatch(
        r"([0-9a-f]{64})  OWNER-MAINTENANCE-WINDOW-WAIVER\.txt", checksum
    )
    if match is None or hashlib.sha256(waiver).hexdigest() != match.group(1):
        raise ValueError("checksum mismatch")
    if not required <= set(waiver.decode("ascii").splitlines()):
        raise ValueError("authorization incomplete")
except (OSError, UnicodeError, ValueError):
    raise SystemExit(1)
PY
}

resume_services() {
    local name
    local remaining=()
    for name in "${paused[@]}"; do
        if ! docker unpause "$name" >/dev/null 2>&1; then
            remaining+=("$name")
        fi
    done
    paused=("${remaining[@]}")
    ((${#paused[@]} == 0))
}

verify_service_recovery() {
    local name status health
    for name in codestra-odoo-1 codestra-n8n-1 codestra-middleware-1 codestra-identity-keycloak-1; do
        for _ in $(seq 1 60); do
            status=$(docker inspect -f '{{.State.Status}}' "$name")
            health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$name")
            if [[ "$status" == running && ( "$health" == healthy || "$health" == not-configured ) ]]; then
                break
            fi
            sleep 2
        done
        test "$status" = running
        if [[ "$health" != not-configured ]]; then test "$health" = healthy; fi
    done
}

cleanup() {
    resume_services || true
    if [[ -d "$work_dir" && ! -L "$work_dir" ]]; then
        find "$work_dir" -type f -delete
        find "$work_dir" -depth -type d -empty -delete
    fi
}

trap cleanup EXIT
trap 'echo "BACKUP_STATUS=FAIL" >&2' ERR

hour=$(TZ=America/New_York date +%H)
if (( 10#$hour < 0 || 10#$hour >= 4 )); then
    if ! validate_owner_window_waiver; then
        echo "refusing to run outside 00:00-04:00 America/New_York without valid owner waiver" >&2
        exit 3
    fi
fi

mkdir -p "$backup_root"
chmod 0700 "$backup_root"
available_bytes=$(df --output=avail -B1 "$backup_root" | tail -n1 | tr -d ' ')
test "$available_bytes" -ge 10737418240

mkdir -p "$work_dir" "$final_dir"
chmod 0700 "$work_dir" "$final_dir"

: > "$work_dir/BACKUP-MANIFEST.tsv"
for container in codestra-postgres-1 codestra-redis-1 codestra-odoo-1 codestra-middleware-1 codestra-n8n-1 codestra-identity-identity-db-1 codestra-identity-keycloak-1 codestra-identity-auth-gateway-1; do
    image_id=$(docker inspect -f '{{.Image}}' "$container")
    status=$(docker inspect -f '{{.State.Status}}' "$container")
    test "$status" = running
    printf '%s\t%s\n' "$container" "$image_id" >> "$work_dir/BACKUP-MANIFEST.tsv"
done

gpg_probe='codestra-readiness-gpg-self-test-v1'
gpg_roundtrip=$(printf '%s' "$gpg_probe" \
    | gpg --homedir /etc/codestra/backup-gpg --batch --yes --trust-model always \
        --recipient 'Codestra Backup Recipient' --encrypt 2>/dev/null \
    | gpg --homedir /etc/codestra/backup-gpg --batch --yes --decrypt 2>/dev/null)
test "$gpg_roundtrip" = "$gpg_probe"

mapfile -t runtime_images < <(awk '{print $2}' "$work_dir/BACKUP-MANIFEST.tsv" | sort -u)
test "${#runtime_images[@]}" -gt 0
docker image save \
    "${runtime_images[@]}" \
    | gzip -n > "$work_dir/runtime-images.tar.gz"

tar -czf "$work_dir/configuration.tar.gz" -C / \
    etc/codestra/secrets \
    etc/caddy \
    opt/codestra/compose/compose.yaml \
    opt/codestra/compose/compose.middleware-runtime.yaml \
    opt/codestra/compose/compose.phase-n2-activation.yaml \
    opt/codestra/compose/compose.final-production-trust.yaml \
    opt/codestra/compose/compose.scraper-ingress-disabled.yaml \
    opt/codestra/compose/compose.health-contract-remediation.yaml \
    opt/codestra/compose/compose.live-delivery-safety.yaml \
    opt/codestra/env \
    opt/codestra/config/odoo \
    opt/codestra/odoo-addons \
    opt/codestra/staging-sources/app-odoo-identity-timezone-57ab123cded2-r2 \
    opt/codestra/identity-platform/deploy/compose.identity.yaml \
    opt/codestra/identity-platform/gateway/oauth2-proxy.cfg \
    opt/codestra/identity-platform/realms/codestra-realm.json

pause_started_ns=$(date +%s%N)
for service in codestra-odoo-1 codestra-n8n-1 codestra-middleware-1 codestra-identity-keycloak-1; do
    test "$(docker inspect -f '{{.State.Status}}' "$service")" = running
    docker pause "$service" >/dev/null
    paused+=("$service")
done

docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_odoo > "$work_dir/odoo.dump"
docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_middleware > "$work_dir/middleware.dump"
docker exec codestra-postgres-1 pg_dump -U postgres -Fc codestra_n8n > "$work_dir/n8n.dump"
docker exec codestra-identity-identity-db-1 pg_dump -U keycloak -Fc keycloak > "$work_dir/keycloak.dump"
ownership_sql="select n.nspname||'.'||c.relname||'|'||c.relkind::text||'|'||r.rolname from pg_class c join pg_namespace n on n.oid=c.relnamespace join pg_roles r on r.oid=c.relowner where n.nspname not in ('pg_catalog','information_schema') and n.nspname !~ '^pg_toast' order by 1"
default_acl_sql="select defaclrole::regrole::text||'|'||coalesce(defaclnamespace::regnamespace::text,'')||'|'||defaclobjtype::text||'|'||defaclacl::text from pg_default_acl order by 1"
for database in codestra_odoo codestra_middleware codestra_n8n; do
    docker exec codestra-postgres-1 psql -U postgres -d "$database" -At -v ON_ERROR_STOP=1 \
        -c "$ownership_sql" > "$work_dir/expected-${database}-owners.txt"
done
docker exec codestra-identity-identity-db-1 psql -U keycloak -d keycloak -At -v ON_ERROR_STOP=1 \
    -c "$ownership_sql" > "$work_dir/expected-keycloak-owners.txt"
docker exec codestra-postgres-1 psql -U postgres -d codestra_middleware -At -v ON_ERROR_STOP=1 \
    -c "$default_acl_sql" > "$work_dir/expected-default-acl.txt"
missing_attachment_checksums=$(docker exec codestra-postgres-1 psql -U postgres -d codestra_odoo -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM ir_attachment WHERE store_fname IS NOT NULL AND (checksum IS NULL OR btrim(checksum) = '')")
test "$missing_attachment_checksums" -eq 0
docker exec codestra-postgres-1 psql -U postgres -d codestra_odoo -At -F '|' -v ON_ERROR_STOP=1 \
    -c "SELECT store_fname, checksum FROM ir_attachment WHERE store_fname IS NOT NULL ORDER BY store_fname" \
    > "$work_dir/odoo-attachments.tsv"

odoo_owner=$(docker run --rm \
    -v codestra_odoo_data:/source/odoo:ro \
    alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce \
    stat -c '%u:%g' /source/odoo)
cat > "$work_dir/ODOO-BACKUP-METADATA" <<EOF
BACKUP_ID=${stamp}
DATABASE=codestra_odoo
FILESTORE_RELATIVE=.local/share/Odoo/filestore/codestra_odoo
ODOO_UID=${odoo_owner%%:*}
ODOO_GID=${odoo_owner##*:}
EOF

docker run --rm \
    -v codestra_odoo_data:/source/odoo:ro \
    -v codestra_n8n_data:/source/n8n:ro \
    -v "$work_dir":/backup \
    alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce \
    sh -ec 'tar -czf /backup/application-volumes.tar.gz -C /source odoo n8n'

resume_services
pause_ended_ns=$(date +%s%N)
pause_duration_ms=$(( (pause_ended_ns - pause_started_ns) / 1000000 ))
verify_service_recovery

(
    cd "$work_dir"
    sha256sum odoo.dump middleware.dump n8n.dump keycloak.dump \
        expected-codestra_odoo-owners.txt expected-codestra_middleware-owners.txt \
        expected-codestra_n8n-owners.txt expected-keycloak-owners.txt expected-default-acl.txt \
        odoo-attachments.tsv ODOO-BACKUP-METADATA \
        application-volumes.tar.gz configuration.tar.gz runtime-images.tar.gz \
        BACKUP-MANIFEST.tsv > SHA256SUMS
    sha256sum -c SHA256SUMS
)

tar -czf "$work_dir/codestra-${stamp}.tar.gz" -C "$work_dir" \
    odoo.dump middleware.dump n8n.dump keycloak.dump \
    expected-codestra_odoo-owners.txt expected-codestra_middleware-owners.txt \
    expected-codestra_n8n-owners.txt expected-keycloak-owners.txt expected-default-acl.txt \
    odoo-attachments.tsv ODOO-BACKUP-METADATA \
    application-volumes.tar.gz configuration.tar.gz runtime-images.tar.gz \
    BACKUP-MANIFEST.tsv SHA256SUMS

gpg --homedir /etc/codestra/backup-gpg --batch --yes --trust-model always \
    --recipient 'Codestra Backup Recipient' \
    --output "$final_dir/codestra-${stamp}.tar.gz.gpg" \
    --encrypt "$work_dir/codestra-${stamp}.tar.gz"

(
    cd "$final_dir"
    sha256sum "codestra-${stamp}.tar.gz.gpg" > SHA256SUMS
    sha256sum -c SHA256SUMS
)

printf 'BACKUP_STATUS=PASS\nBACKUP_TIMESTAMP=%s\nBACKUP_DIRECTORY=%s\nPRODUCTION_SERVICE_RECOVERY_GATE=PASS\nCONSISTENCY_PAUSE_DURATION_MS=%s\nCONFIGURATION_SCOPE_GATE=PASS_EXACT_ACTIVE_PATHS\nLOCAL_RUNTIME_IMAGE_BACKUP_GATE=PASS\nUNATTENDED_GPG_ROUNDTRIP_GATE=PASS\n' \
    "$stamp" "$final_dir" "$pause_duration_ms" > "$final_dir/STATUS.txt"
(cd "$final_dir" && sha256sum "codestra-${stamp}.tar.gz.gpg" SHA256SUMS STATUS.txt > EVIDENCE-SHA256SUMS && sha256sum -c EVIDENCE-SHA256SUMS)
printf '%s\n' "$stamp" > "$backup_root/.LAST_SUCCESS-${stamp}"
mv "$backup_root/.LAST_SUCCESS-${stamp}" "$backup_root/LAST_SUCCESS"
printf '%s\n' "$final_dir"
