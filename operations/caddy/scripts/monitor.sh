#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT=${CADDY_METRICS_FILE:-/var/lib/node_exporter/textfile_collector/caddy_production.prom}
TMP=$(mktemp "${OUT}.XXXXXX")
trap 'find "$TMP" -delete 2>/dev/null || true' EXIT
now=$(date +%s)
systemctl is-active --quiet caddy && up=1 || up=0
echo "codestra_caddy_service_up $up" >"$TMP"
"$ROOT/scripts/diff-live.sh" >/tmp/caddy-drift-monitor.out 2>&1 && drift=0 || drift=$(awk -F= '/CADDY_UNEXPECTED_DRIFT/{print $2}' /tmp/caddy-drift-monitor.out)
echo "codestra_caddy_unexpected_drift ${drift:-1}" >>"$TMP"
latest=$(find /var/backups/caddy -maxdepth 1 -type f -name 'caddy-state-*.tar.gpg' -printf '%T@\n' 2>/dev/null | sort -nr | head -1)
age=999999; [ -n "$latest" ] && age=$((now-${latest%.*}))
echo "codestra_caddy_backup_age_seconds $age" >>"$TMP"
echo "codestra_caddy_restarts_total $(systemctl show caddy -p NRestarts --value)" >>"$TMP"
renewal_errors=$(journalctl -u caddy --since '15 minutes ago' --no-pager | grep -Eci 'renew.*fail|challenge.*fail|storage.*permission|certificate.*error' || true)
reload_errors=$(journalctl -u caddy --since '15 minutes ago' --no-pager | grep -Eci 'reload.*fail|adapt.*error|validation.*fail' || true)
echo "codestra_caddy_certificate_renewal_errors $renewal_errors" >>"$TMP"
echo "codestra_caddy_reload_errors $reload_errors" >>"$TMP"
while IFS=$'\t' read -r host scope tls mtls rest; do
  [ "$host" = host ] && continue
  curl_args=(-sS --max-time 10 -o /dev/null -w '%{http_code} %{time_total}')
  [ "$scope" = internal ] && curl_args+=(-k --resolve "$host:443:65.109.65.169")
  result=$(curl "${curl_args[@]}" "https://$host/" 2>/dev/null || echo '000 0')
  code=${result%% *}; case "$code" in 200|201|202|204|301|302|303|307|308|401|403|404) ok=1;; *) ok=0;; esac
  [ "$mtls" = yes ] && [ "$code" = 000 ] && ok=1
  echo "codestra_caddy_https_expected_response{host=\"$host\",scope=\"$scope\"} $ok" >>"$TMP"
  echo "codestra_caddy_canary_latency_seconds{boundary=\"edge\",host=\"$host\"} ${result##* }" >>"$TMP"
done <"$ROOT/HOST-OWNERSHIP.tsv"
for host in api.staging.internal.codestra.agency auth.staging.internal.codestra.agency n8n.staging.internal.codestra.agency odoo.staging.internal.codestra.agency; do
  end=$(timeout 5 openssl s_client -connect 65.109.65.169:443 -servername "$host" </dev/null 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  hours=0; [ -n "$end" ] && hours=$(( ($(date -d "$end" +%s)-now)/3600 ))
  echo "codestra_caddy_internal_certificate_hours_remaining{host=\"$host\"} $hours" >>"$TMP"
done
for host in middleware.internal.codestra.agency middleware-staging.internal.codestra.agency; do
  code=$(curl -ksS --resolve "$host:443:65.109.65.169" --cert /etc/codestra/pki/vicidial-observer-enrollment/controller-middleware.crt --key /etc/codestra/pki/vicidial-observer-enrollment/controller-middleware.key -o /dev/null -w '%{http_code}' "https://$host/health" 2>/dev/null || echo 000)
  case "$code" in 200|202|204|400|401|403|404|405) ok=1;; *) ok=0;; esac
  echo "codestra_caddy_mtls_authorized_handshake_ok{host=\"$host\"} $ok" >>"$TMP"
done
for file in /var/log/caddy/*.log; do
  [ -s "$file" ] || continue; boundary=${file##*/}; boundary=${boundary%.log}
  count=$(tail -1000 "$file" | jq -s '[.[]|select(.status>=500)]|length' 2>/dev/null || echo 0)
  echo "codestra_caddy_recent_5xx{boundary=\"$boundary\"} $count" >>"$TMP"
done
for host in api.codestra.agency api.codestra.co auth.codestra.co crm.codestra.agency n8n.codestra.agency phone.codestra.agency; do
  code=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://$host/" 2>/dev/null || echo 000)
  case "$code" in 301|302|307|308) ok=1;; *) ok=0;; esac
  echo "codestra_caddy_http_redirect_ok{host=\"$host\"} $ok" >>"$TMP"
done
for host in api.codestra.agency api.codestra.co; do
  result=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{time_total}' "https://$host/" 2>/dev/null || echo '000 0')
  echo "codestra_caddy_kong_canary_ok{host=\"$host\"} $(echo "$result"|awk '$1~/^(200|401|403|404)$/{print 1;next}{print 0}')" >>"$TMP"
done
ws_nonce=$(head -c 16 /dev/urandom | base64)
ws=$(curl -sk --http1.1 --max-time 10 -o /dev/null -w '%{http_code} %{time_total}' -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H "Sec-WebSocket-Key: $ws_nonce" https://api.codestra.co/ws/agent || echo '000 0')
echo "codestra_caddy_websocket_expected_response $(echo "$ws"|awk '$1~/^(101|401|403|426)$/{print 1;next}{print 0}')" >>"$TMP"
echo "codestra_caddy_canary_latency_seconds{boundary=\"websocket\",host=\"api.codestra.co\"} ${ws##* }" >>"$TMP"
mv "$TMP" "$OUT"; chmod 0644 "$OUT"
echo CADDY_MONITORING=PASS
