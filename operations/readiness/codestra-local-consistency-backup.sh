#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=/opt/codestra/backups/production-readiness-local
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work_dir="${backup_root}/.work-${stamp}"
final_dir="${backup_root}/${stamp}"
paused=()

resume_services() {
    local name
    for name in "${paused[@]}"; do
        docker unpause "$name" >/dev/null 2>&1 || true
    done
    paused=()
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
    resume_services
    if [[ -d "$work_dir" && ! -L "$work_dir" ]]; then
        find "$work_dir" -type f -delete
        find "$work_dir" -depth -type d -empty -delete
    fi
}

trap cleanup EXIT
trap 'echo "BACKUP_STATUS=FAIL" >&2' ERR

hour=$(TZ=America/New_York date +%H)
if (( 10#$hour < 0 || 10#$hour >= 4 )); then
    echo "refusing to run outside 00:00-04:00 America/New_York" >&2
    exit 3
fi

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

middleware_image=$(docker inspect -f '{{.Image}}' codestra-middleware-1)
docker image save \
    "$middleware_image" \
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
        application-volumes.tar.gz configuration.tar.gz runtime-images.tar.gz \
        BACKUP-MANIFEST.tsv > SHA256SUMS
    sha256sum -c SHA256SUMS
)

tar -czf "$work_dir/codestra-${stamp}.tar.gz" -C "$work_dir" \
    odoo.dump middleware.dump n8n.dump keycloak.dump \
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
printf '%s\n' "$final_dir"
