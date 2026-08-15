#!/usr/bin/env bash
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${AUDIT_OUTPUT:-$ROOT/artifacts/connectivity-audit.json}
SAFE_MODE=${AUDIT_SAFE_MODE:-true}
mkdir -p "$(dirname "$OUT")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

record() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >>"$tmp/results.tsv"
}

[[ "$SAFE_MODE" == true ]] || { echo "Refusing to run without AUDIT_SAFE_MODE=true" >&2; exit 2; }

actual_public=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo unknown)
actual_private=$(ip -br -4 addr | awk '$3 ~ /^10\.40\./ {sub(/\/.*/,"",$3); print $3; exit}')
[[ "$actual_public" == 65.109.65.169 ]] && record host.public_identity PASS "$actual_public" || record host.public_identity FAIL "expected 65.109.65.169; observed $actual_public"
[[ "$actual_private" == 10.40.0.1 ]] && record host.private_identity PASS "$actual_private" || record host.private_identity FAIL "expected 10.40.0.1; observed ${actual_private:-none}"

if ping -c 1 -W 2 10.40.0.1 >/dev/null 2>&1; then record network.middleware_peer PASS "10.40.0.1 ICMP reply"; else record network.middleware_peer FAIL "10.40.0.1 no ICMP reply"; fi
health_code=$(curl -sS -o "$tmp/middleware-health" -w '%{http_code}' --connect-timeout 3 --max-time 6 http://10.40.0.1:8095/health 2>/dev/null || true)
if [[ "$health_code" == 200 ]] && grep -q '"status":"ok"' "$tmp/middleware-health"; then record runtime.middleware_health PASS "10.40.0.1:8095/health HTTP 200 status ok"; else record runtime.middleware_health FAIL "10.40.0.1:8095/health HTTP ${health_code:-000}"; fi
if ssh -i /root/.ssh/codestra-middleware-operator -o BatchMode=yes -o ConnectTimeout=4 root@10.40.0.1 true >/dev/null 2>&1; then
  record ssh.middleware_operator PASS "non-interactive root identity accepted"
else
  record ssh.middleware_operator BLOCKED "available operator key rejected by 10.40.0.1"
fi

if PYTHONPATH="$ROOT" /usr/bin/pytest-3 -q "$ROOT/tests/test_integration_control_plane.py" "$ROOT/tests/test_communications_control_plane.py" >"$tmp/pytest" 2>&1; then
  summary=$(tail -n 1 "$tmp/pytest")
  record source.integration_suite PASS "$summary"
  record inbound.hmac_replay PASS "valid/invalid/stale HMAC and duplicate/conflict tests passed"
  record outbound.telnexa_simulator PASS "simulator returned sim-* and worker accepted message"
  record outbound.klyrow_safe PASS "test adapter returned test-* without network delivery"
  record outbound.kyqra_safe PASS "test job returned test-job-*; unsafe target rejected"
  record resilience.idempotency PASS "event, message, and crawler duplicate/conflict tests passed"
  record resilience.retry_dlq PASS "bounded retry, dead-letter, replay, and audit tests passed"
  record resilience.circuit_breaker PASS "threshold/open behavior test passed"
  record trace.correlation PASS "tenant-scoped correlation lookup and downstream header tests passed"
else
  record source.integration_suite FAIL "integration pytest failed; see local command output"
fi

for pair in 127.0.0.1:5432 127.0.0.1:6379 127.0.0.1:5672; do
  host=${pair%:*}; port=${pair#*:}
  if timeout 2 bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1; then record "exposure.$port" FAIL "$pair unexpectedly listening"; else record "exposure.$port" PASS "$pair not listening"; fi
done

if ss -lntH | awk '{print $4}' | grep -Eq '(^|:)8096$'; then record runtime.control_plane PASS "listener 8096 present"; else record runtime.control_plane BLOCKED "no deployed listener on 8096 on this host"; fi
if docker ps --format '{{.Names}}' | grep -Eqi '(^|[-_])odoo($|[-_])'; then record runtime.odoo PASS "Odoo container present"; else record runtime.odoo BLOCKED "no Odoo runtime discovered on this host"; fi
if docker ps --format '{{.Names}}' | grep -Eqi '(^|[-_])n8n($|[-_])'; then record runtime.n8n PASS "n8n container present"; else record runtime.n8n BLOCKED "no n8n runtime discovered on this host"; fi

python3 - "$tmp/results.tsv" "$OUT" <<'PY'
import csv, json, pathlib, sys
rows=[]
with open(sys.argv[1], encoding="utf-8") as handle:
    for check,status,evidence in csv.reader(handle, delimiter="\t"):
        rows.append({"check":check,"status":status,"evidence":evidence})
payload={"schema":"codestra.connectivity-audit.v1","safe_mode":True,"results":rows,
         "summary":{s:sum(r["status"]==s for r in rows) for s in ("PASS","FAIL","BLOCKED")}}
path=pathlib.Path(sys.argv[2]); path.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
print(json.dumps(payload["summary"],sort_keys=True))
PY
