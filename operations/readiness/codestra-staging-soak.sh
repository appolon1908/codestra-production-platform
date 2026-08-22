#!/usr/bin/env bash
set -euo pipefail
umask 077

staging_root=/opt/codestra/evidence/production-readiness-staging
evidence_root=/opt/codestra/evidence/production-readiness-soak
acceptance=$(find "$staging_root" -mindepth 2 -maxdepth 2 -type f -name STAGING-ACCEPTANCE.txt -print0 \
    | xargs -0 -r grep -l '^ISOLATED_STAGING_INSTALL_GATE=PASS$' | sort | tail -n1)
test -n "$acceptance"
acceptance_dir=$(dirname "$acceptance")
(cd "$acceptance_dir" && sha256sum -c SHA256SUMS)

stamp=$(date -u +%Y%m%dT%H%M%SZ)
final_dir="${evidence_root}/${stamp}"
mkdir -p "$final_dir"
chmod 0700 "$final_dir"
cp "$acceptance_dir/CONTAINER-BASELINE.tsv" "$final_dir/CONTAINER-BASELINE.tsv"
: > "$final_dir/SOAK-SAMPLES.tsv"
: > "$final_dir/SOAK-HTTP.tsv"
ca=/var/lib/caddy/caddy/pki/authorities/local/root.crt
openssl x509 -in "$ca" -noout -checkend 86400 >/dev/null
proxy_ip=127.0.0.1

start_epoch=$(date +%s)
end_epoch=$((start_epoch + 86400))
sample_count=0
while (( $(date +%s) <= end_epoch )); do
    while IFS=$'\t' read -r container _ _ baseline_restarts; do
        status=$(docker inspect -f '{{.State.Status}}' "$container")
        health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$container")
        restarts=$(docker inspect -f '{{.RestartCount}}' "$container")
        test "$status" = running
        if [[ "$health" != not-configured ]]; then test "$health" = healthy; fi
        test "$restarts" = "$baseline_restarts"
        printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$container" "$status" "$health" "$restarts" >> "$final_dir/SOAK-SAMPLES.tsv"
    done < "$final_dir/CONTAINER-BASELINE.tsv"
    for spec in \
        'odoo.staging.internal.codestra.agency /web/health' \
        'api.staging.internal.codestra.agency /healthz' \
        'n8n.staging.internal.codestra.agency /healthz' \
        'auth.staging.internal.codestra.agency /realms/master'; do
        read -r host path <<< "$spec"
        code=$(curl --cacert "$ca" --max-time 10 --resolve "${host}:443:${proxy_ip}" -sS -o /dev/null -w '%{http_code}' "https://${host}${path}")
        test "$code" = 200
        printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "${host}${path}" "$code" >> "$final_dir/SOAK-HTTP.tsv"
    done
    sample_count=$((sample_count + 1))
    now=$(date +%s)
    (( now >= end_epoch )) && break
    sleep 300
done

elapsed=$(( $(date +%s) - start_epoch ))
test "$elapsed" -ge 86400
test "$sample_count" -ge 280
cat > "$final_dir/SOAK-RESULT.txt" <<EOF
STAGING_SOAK_GATE=PASS
SOAK_DURATION_SECONDS=${elapsed}
SOAK_SAMPLE_COUNT=${sample_count}
RESTART_DELTA_GATE=PASS
HEALTH_CONTINUITY_GATE=PASS
FUNCTIONAL_INGRESS_CONTINUITY_GATE=PASS
INTERNAL_TLS_CONTINUITY_GATE=PASS
PRODUCTION_DEPLOYMENT_GATE=BLOCKED_PENDING_SEPARATE_AUTHORIZATION
EOF
(cd "$final_dir" && sha256sum CONTAINER-BASELINE.tsv SOAK-SAMPLES.tsv SOAK-HTTP.tsv SOAK-RESULT.txt > SHA256SUMS && sha256sum -c SHA256SUMS)
printf '%s\n' "$final_dir"
