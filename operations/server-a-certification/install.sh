#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

mode=${1:---check}
case "$mode" in
  --check|--apply) ;;
  *) echo "usage: $0 [--check|--apply]" >&2; exit 2 ;;
esac

source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
package_root="$source_root/operations/server-a-certification"
database_root="$source_root/operations/database-certification"

python3 "$package_root/validate-source.py"
python3 -m compileall -q "$package_root" "$database_root"

for script in "$package_root"/*.sh; do
  bash -n "$script"
done

if [[ "$mode" == --check ]]; then
  printf 'SERVER_A_INSTALL_CHECK=PASS\nSOURCE_ROOT=%s\n' "$source_root"
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "install requires root" >&2; exit 2; }
[[ ${CODESTRA_SERVER_A_INSTALL_CONFIRM:-} == INSTALL_REPOSITORY_CONTROLS ]] || {
  echo "typed install confirmation is missing" >&2
  exit 2
}
expected_sha=${CODESTRA_EXPECTED_SOURCE_SHA:-}
[[ $expected_sha =~ ^[0-9a-f]{40}$ ]] || { echo "exact expected source SHA is required" >&2; exit 2; }
actual_sha=$(git -C "$source_root" rev-parse HEAD)
[[ "$actual_sha" == "$expected_sha" ]] || { echo "checkout does not match expected source SHA" >&2; exit 2; }
[[ -z $(git -C "$source_root" status --porcelain=v1) ]] || { echo "checkout must be clean" >&2; exit 2; }

control_root=${CODESTRA_PRODUCTION_CONTROL_ROOT:-/opt/codestra/production-controls}
evidence_root=${CODESTRA_SERVER_A_EVIDENCE_ROOT:-/opt/codestra/evidence/server-a-certification}
rollback_root=${CODESTRA_SERVER_A_ROLLBACK_ROOT:-/opt/codestra/rollback/server-a-certification}
rule_root=${CODESTRA_PROMETHEUS_RULE_DIRECTORY:-/opt/codestra/monitoring/rules}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
release="$control_root/releases/$actual_sha"
staging="$control_root/releases/.${actual_sha}.partial"
transaction="$rollback_root/$stamp"

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

install -d -m 0700 "$control_root/releases" "$evidence_root/install" "$transaction/units" "$transaction/rules"
capture_ssh_state "$transaction/ssh-before.json"
for unit in "${units[@]}"; do
  if systemctl is-active --quiet "$unit" || systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    echo "two-stage install refuses to replace an active or enabled control unit: $unit" >&2
    echo "use the existing rollback/upgrade procedure before installing a new release" >&2
    exit 2
  fi
done
previous_current=$(readlink "$control_root/current" 2>/dev/null || true)
printf '%s\n' "$previous_current" > "$transaction/previous-current"

for unit in "${units[@]}"; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    cp -a "/etc/systemd/system/$unit" "$transaction/units/$unit"
  else
    : > "$transaction/units/$unit.absent"
  fi
done
for rule in "${rules[@]}"; do
  if [[ -f "$rule_root/$rule" ]]; then
    cp -a "$rule_root/$rule" "$transaction/rules/$rule"
  else
    : > "$transaction/rules/$rule.absent"
  fi
done

rollback_install() {
  set +e
  rm -f "$control_root/current"
  if [[ -n "$previous_current" ]]; then
    ln -s "$previous_current" "$control_root/current"
  fi
  for unit in "${units[@]}"; do
    if [[ -f "$transaction/units/$unit" ]]; then
      install -m 0644 "$transaction/units/$unit" "/etc/systemd/system/$unit"
    else
      rm -f "/etc/systemd/system/$unit"
    fi
  done
  for rule in "${rules[@]}"; do
    if [[ -f "$transaction/rules/$rule" ]]; then
      install -m 0644 "$transaction/rules/$rule" "$rule_root/$rule"
    else
      rm -f "$rule_root/$rule"
    fi
  done
  systemctl daemon-reload || true
  rm -rf "$staging"
}
trap rollback_install ERR

rm -rf "$staging"
install -d -m 0755 "$staging/operations/database-certification" "$staging/operations/server-a-certification"
cp -a "$database_root"/. "$staging/operations/database-certification/"
cp -a "$package_root"/. "$staging/operations/server-a-certification/"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -name '*.py' -exec chmod 0755 {} +
find "$staging" -type f -name '*.sh' -exec chmod 0755 {} +
find "$staging" -type f ! -name '*.py' ! -name '*.sh' -exec chmod 0644 {} +
find "$staging" -type d -name __pycache__ -prune -exec rm -rf {} +

python3 "$staging/operations/server-a-certification/validate-source.py"
if [[ -e "$release" ]]; then
  diff -qr "$release" "$staging" >/dev/null || {
    echo "existing release path differs from candidate source" >&2
    exit 1
  }
  rm -rf "$staging"
else
  mv "$staging" "$release"
fi

install -d -m 0755 "$rule_root"
for unit in "$database_root"/systemd/* "$package_root"/systemd/*; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
install -m 0644 "$database_root/database-certification.rules.yml" "$rule_root/database-certification.rules.yml"
install -m 0644 "$package_root/centrifugo.rules.yml" "$rule_root/centrifugo.rules.yml"
install -m 0644 "$package_root/governance.rules.yml" "$rule_root/governance.rules.yml"
install -m 0644 "$package_root/container-policy.rules.yml" "$rule_root/container-policy.rules.yml"
install -m 0644 "$package_root/environment-isolation.rules.yml" "$rule_root/environment-isolation.rules.yml"
install -m 0644 "$package_root/database-security.rules.yml" "$rule_root/database-security.rules.yml"
install -m 0644 "$package_root/realtime-ha.rules.yml" "$rule_root/realtime-ha.rules.yml"
install -m 0644 "$package_root/odoo-copy-governance.rules.yml" "$rule_root/odoo-copy-governance.rules.yml"
install -m 0644 "$package_root/redis-recovery.rules.yml" "$rule_root/redis-recovery.rules.yml"
install -m 0644 "$package_root/runtime-source-lock.rules.yml" "$rule_root/runtime-source-lock.rules.yml"

next_link="$control_root/.current-$stamp"
ln -s "releases/$actual_sha" "$next_link"
mv -Tf "$next_link" "$control_root/current"
systemctl daemon-reload

capture_ssh_state "$transaction/ssh-after.json"
assert_ssh_unchanged "$transaction/ssh-before.json" "$transaction/ssh-after.json"

python3 - "$transaction" "$actual_sha" "$previous_current" "$rule_root" <<'PY'
import hashlib, json, sys
from pathlib import Path
root=Path(sys.argv[1])
files=[]
for path in sorted(root.rglob('*')):
    if path.is_file():
        files.append({"path":str(path.relative_to(root)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size})
payload={
  "schema":"codestra.server-a-install-result.v1",
  "status":"PASS",
  "source_commit":sys.argv[2],
  "previous_current":sys.argv[3],
  "prometheus_rule_directory":sys.argv[4],
  "ssh_changed":False,
  "services_started":False,
  "files":files,
}
(root/'INSTALL-RESULT.json').write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n')
PY
chmod 0600 "$transaction/INSTALL-RESULT.json"
printf '%s\n' "$transaction" > "$control_root/LAST_INSTALL_TRANSACTION"
chmod 0600 "$control_root/LAST_INSTALL_TRANSACTION"
trap - ERR
printf 'SERVER_A_REPOSITORY_CONTROLS_INSTALLED=PASS\nSOURCE_SHA=%s\nRELEASE=%s\nROLLBACK_TRANSACTION=%s\nSERVICES_STARTED=NO\nSSH_CHANGED=NO\n' \
  "$actual_sha" "$release" "$transaction"
