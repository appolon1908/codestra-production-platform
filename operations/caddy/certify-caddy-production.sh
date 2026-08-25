#!/usr/bin/env bash
set -o pipefail

PUBLIC_MIN_DAYS="${PUBLIC_MIN_DAYS:-7}"
INTERNAL_MIN_HOURS="${INTERNAL_MIN_HOURS:-2}"

pass=0
warn=0
fail=0

check_pass() { printf 'PASS: %s\n' "$1"; pass=$((pass + 1)); }
check_warn() { printf 'WARN: %s\n' "$1"; warn=$((warn + 1)); }
check_fail() { printf 'FAIL: %s\n' "$1"; fail=$((fail + 1)); }

is_internal_pki_host() {
    case "$1" in
        api.staging.internal.codestra.agency | \
        auth.staging.internal.codestra.agency | \
        n8n.staging.internal.codestra.agency | \
        odoo.staging.internal.codestra.agency)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

if systemctl is-active --quiet caddy; then
    check_pass "Caddy service active"
else
    check_fail "Caddy service not active"
fi

if caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
    check_pass "Caddy configuration valid"
else
    check_fail "Caddy configuration invalid"
fi

adapted="$(caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null)"
if [ -z "$adapted" ]; then
    check_fail "Caddy configuration could not be adapted"
    hosts=""
else
    # Read only actual HTTP host matchers from Caddy's adapted JSON. Do not
    # scrape filenames, log paths, comments, header placeholders, or CSP URLs.
    hosts="$(
        printf '%s\n' "$adapted" |
            jq -r '
                .. | objects | .host? // empty |
                if type == "array" then .[] else . end
            ' |
            sort -u
    )"
fi

printf '===== REAL CADDY HOSTS =====\n%s\n' "$hosts"

now_epoch="$(date +%s)"
for host in $hosts; do
    certificate="$(
        timeout 8 openssl s_client \
            -connect "${host}:443" \
            -servername "$host" \
            </dev/null 2>/dev/null |
            openssl x509 -noout -issuer -enddate 2>/dev/null
    )"

    if [ -z "$certificate" ]; then
        check_warn "$host certificate unreadable or requires client authentication"
        continue
    fi

    issuer="$(printf '%s\n' "$certificate" | sed -n 's/^issuer=//p')"
    expiry="$(printf '%s\n' "$certificate" | sed -n 's/^notAfter=//p')"
    expiry_epoch="$(date -d "$expiry" +%s 2>/dev/null || printf '0')"

    if [ "$expiry_epoch" -le 0 ]; then
        check_warn "$host certificate expiry could not be parsed"
        continue
    fi

    seconds_remaining=$((expiry_epoch - now_epoch))
    if is_internal_pki_host "$host"; then
        hours_remaining=$((seconds_remaining / 3600))
        if [ "$hours_remaining" -gt "$INTERNAL_MIN_HOURS" ]; then
            check_pass "$host internal certificate valid (${hours_remaining}h remaining)"
        else
            check_fail "$host internal certificate dangerously close to expiry (${hours_remaining}h remaining)"
        fi
    else
        days_remaining=$((seconds_remaining / 86400))
        if [ "$days_remaining" -gt 30 ]; then
            check_pass "$host public certificate >30 days (${days_remaining}d remaining)"
        elif [ "$days_remaining" -gt "$PUBLIC_MIN_DAYS" ]; then
            check_warn "$host public certificate expires within 30 days (${days_remaining}d remaining)"
        else
            check_fail "$host public certificate expires within 7 days (${days_remaining}d remaining; issuer=${issuer})"
        fi
    fi
done

restarts="$(systemctl show caddy -p NRestarts --value)"
if [ "${restarts:-0}" -eq 0 ] 2>/dev/null; then
    check_pass "No Caddy service restart loop"
else
    check_warn "Caddy restart count is $restarts"
fi

printf 'PASS=%s\nWARN=%s\nFAIL=%s\n' "$pass" "$warn" "$fail"
if [ "$fail" -eq 0 ]; then
    echo 'CADDY_CERTIFICATION=PASS'
    exit 0
fi

echo 'CADDY_CERTIFICATION=FAIL'
exit 1
