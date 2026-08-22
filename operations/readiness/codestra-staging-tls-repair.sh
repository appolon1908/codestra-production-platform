#!/usr/bin/env bash
set -euo pipefail
umask 077

# The active edge is host Caddy. The legacy Compose reverse-proxy is retired;
# readiness validates the active edge without recreating containers.
caddyfile=/etc/caddy/Caddyfile
ca=/var/lib/caddy/caddy/pki/authorities/local/root.crt
public_ip=65.109.65.169

systemctl is-active --quiet caddy
caddy validate --config "$caddyfile" >/dev/null
openssl x509 -in "$ca" -noout -checkend 172800 >/dev/null

verify_route() {
    local host=$1 path=$2 trust=$3 address code
    if [[ "$trust" == internal ]]; then
        address=127.0.0.1
        code=$(curl --cacert "$ca" --max-time 10 --resolve "${host}:443:${address}" -sS -o /dev/null -w '%{http_code}' "https://${host}${path}")
    else
        address=$public_ip
        code=$(curl --max-time 10 --resolve "${host}:443:${address}" -sS -o /dev/null -w '%{http_code}' "https://${host}${path}")
    fi
    [[ "$code" == 200 ]]
}

while read -r host path trust; do
    verify_route "$host" "$path" "$trust"
done <<'EOF'
crm.codestra.agency /web/health public
api.codestra.agency /healthz public
n8n.codestra.agency /healthz public
auth.codestra.co /realms/master public
phone.codestra.agency /ping public
odoo.staging.internal.codestra.agency /web/health internal
api.staging.internal.codestra.agency /healthz internal
n8n.staging.internal.codestra.agency /healthz internal
auth.staging.internal.codestra.agency /realms/master internal
EOF

stamp=$(date -u +%Y%m%dT%H%M%SZ)
final_dir="/opt/codestra/evidence/production-readiness-staging-tls/${stamp}"
mkdir -p "$final_dir"
chmod 0700 "$final_dir"
caddyfile_sha=$(sha256sum "$caddyfile" | awk '{print $1}')
cat > "$final_dir/STAGING-TLS-RESULT.txt" <<EOF
STAGING_INTERNAL_TLS_REPAIR_GATE=PASS
STAGING_INTERNAL_TLS_TRUST_GATE=PASS
PRODUCTION_INGRESS_REGRESSION_GATE=PASS
CADDYFILE_SHA256=${caddyfile_sha}
EDGE_RUNTIME=host-caddy
EOF
(cd "$final_dir" && sha256sum STAGING-TLS-RESULT.txt > SHA256SUMS && sha256sum -c SHA256SUMS)
printf '%s\n' "$final_dir"
