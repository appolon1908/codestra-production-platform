#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ ${1:-} == --apply ]] || { echo "usage: $0 --apply <install-transaction-directory>" >&2; exit 2; }
transaction=${2:-}
[[ $EUID -eq 0 ]] || { echo "rollback requires root" >&2; exit 2; }
[[ ${CODESTRA_SERVER_A_ROLLBACK_CONFIRM:-} == ROLLBACK_SERVER_A_CONTROLS ]] || {
  echo "typed rollback confirmation is missing" >&2
  exit 2
}
rollback_root=${CODESTRA_SERVER_A_ROLLBACK_ROOT:-/opt/codestra/rollback/server-a-certification}
transaction=$(realpath -e "$transaction")
case "$transaction" in
  "$rollback_root"/*) ;;
  *) echo "transaction is outside the approved rollback root" >&2; exit 2 ;;
esac
[[ -f "$transaction/INSTALL-RESULT.json" ]] || { echo "install result is missing" >&2; exit 2; }

source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
package_root="$source_root/operations/server-a-certification"
control_root=${CODESTRA_PRODUCTION_CONTROL_ROOT:-/opt/codestra/production-controls}
rule_root=$(python3 - "$transaction/INSTALL-RESULT.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['prometheus_rule_directory'])
PY
)
previous_current=$(cat "$transaction/previous-current")

units=(
  codestra-database-certification-backup.service
  codestra-database-certification-backup.timer
  codestra-database-certification-restore.service
  codestra-database-certification-restore.timer
  codestra-database-certification-metrics.service
  codestra-database-certification-metrics.timer
  codestra-centrifugo-probe.service
  codestra-centrifugo-probe.timer
  codestra-financial-governance-publisher.service
  codestra-financial-governance-publisher.timer
  codestra-container-policy-audit.service
  codestra-container-policy-audit.timer
  codestra-environment-isolation-audit.service
  codestra-environment-isolation-audit.timer
  codestra-database-security-audit.service
  codestra-database-security-audit.timer
  codestra-realtime-ha-audit.service
  codestra-realtime-ha-audit.timer
  codestra-odoo-copy-governance-audit.service
  codestra-odoo-copy-governance-audit.timer
  codestra-redis-recovery-audit.service
  codestra-redis-recovery-audit.timer
  codestra-runtime-source-lock-audit.service
  codestra-runtime-source-lock-audit.timer
)
rules=(
  database-certification.rules.yml
  centrifugo.rules.yml
  governance.rules.yml
  container-policy.rules.yml
  environment-isolation.rules.yml
  database-security.rules.yml
  realtime-ha.rules.yml
  odoo-copy-governance.rules.yml
  redis-recovery.rules.yml
  runtime-source-lock.rules.yml
)

capture_ssh_state() {
  local output=$1
  python3 - "$package_root/firewall/server-a-firewall.py" "$output" <<'PY'
import importlib.util, json, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("server_a_firewall", sys.argv[1])
assert spec and spec.loader
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
Path(sys.argv[2]).write_text(json.dumps(module.ssh_state(),sort_keys=True,indent=2)+"\n")
PY
  chmod 0600 "$output"
}

assert_ssh_unchanged() {
  local before=$1 after=$2
  python3 - "$package_root/firewall/server-a-firewall.py" "$before" "$after" <<'PY'
import importlib.util, json, sys
spec=importlib.util.spec_from_file_location("server_a_firewall", sys.argv[1])
assert spec and spec.loader
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with open(sys.argv[2], encoding="utf-8") as handle:
    before=json.load(handle)
with open(sys.argv[3], encoding="utf-8") as handle:
    after=json.load(handle)
module.assert_ssh_state_unchanged(before, after)
PY
}

capture_ssh_state "$transaction/rollback-ssh-before.json"
for unit in "${units[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
done
for unit in "${units[@]}"; do
  if [[ -f "$transaction/units/$unit" ]]; then
    install -m 0644 "$transaction/units/$unit" "/etc/systemd/system/$unit"
  elif [[ -f "$transaction/units/$unit.absent" ]]; then
    rm -f "/etc/systemd/system/$unit"
  else
    echo "unit rollback evidence is incomplete: $unit" >&2
    exit 1
  fi
done
for rule in "${rules[@]}"; do
  if [[ -f "$transaction/rules/$rule" ]]; then
    install -m 0644 "$transaction/rules/$rule" "$rule_root/$rule"
  elif [[ -f "$transaction/rules/$rule.absent" ]]; then
    rm -f "$rule_root/$rule"
  else
    echo "rule rollback evidence is incomplete: $rule" >&2
    exit 1
  fi
done
rm -f "$control_root/current"
if [[ -n "$previous_current" ]]; then
  ln -s "$previous_current" "$control_root/current"
fi
systemctl daemon-reload
capture_ssh_state "$transaction/rollback-ssh-after.json"
assert_ssh_unchanged "$transaction/rollback-ssh-before.json" "$transaction/rollback-ssh-after.json"
python3 - "$transaction" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path=Path(sys.argv[1])/'ROLLBACK-RESULT.json'
path.write_text(json.dumps({
  'schema':'codestra.server-a-controls-rollback-result.v1',
  'status':'PASS',
  'timestamp':datetime.now(timezone.utc).isoformat(),
  'ssh_changed':False,
  'release_artifacts_deleted':False,
},sort_keys=True,indent=2)+'\n')
PY
chmod 0600 "$transaction/ROLLBACK-RESULT.json"
printf 'SERVER_A_REPOSITORY_CONTROLS_ROLLBACK=PASS\nTRANSACTION=%s\nSSH_CHANGED=NO\n' "$transaction"
