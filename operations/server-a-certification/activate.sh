#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ ${1:-} == --apply ]] || { echo "usage: $0 --apply" >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "activation requires root" >&2; exit 2; }
[[ ${CODESTRA_SERVER_A_ACTIVATE_CONFIRM:-} == ACTIVATE_SERVER_A_CONTROLS ]] || {
  echo "typed activation confirmation is missing" >&2
  exit 2
}

control_root=${CODESTRA_PRODUCTION_CONTROL_ROOT:-/opt/codestra/production-controls}
current=$(realpath -e "$control_root/current")
package_root="$current/operations/server-a-certification"
evidence_root=${CODESTRA_SERVER_A_EVIDENCE_ROOT:-/opt/codestra/evidence/server-a-certification}
backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
restore_root=${CODESTRA_DATABASE_RESTORE_ROOT:-/opt/codestra/evidence/database-restore}
config_root=${CODESTRA_SERVER_A_CONFIG_ROOT:-/etc/codestra/server-a-certification}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
transaction="$evidence_root/activation/$stamp"
install -d -m 0700 "$transaction" "$transaction/centrifugo" "$transaction/governance"

periodic_timers=(
  codestra-database-certification-backup.timer
  codestra-database-certification-restore.timer
  codestra-database-certification-metrics.timer
  codestra-centrifugo-probe.timer
  codestra-financial-governance-publisher.timer
  codestra-database-security-audit.timer
  codestra-realtime-ha-audit.timer
  codestra-odoo-copy-governance-audit.timer
  codestra-redis-recovery-audit.timer
  codestra-runtime-source-lock-audit.timer
  codestra-container-policy-audit.timer
  codestra-environment-isolation-audit.timer
)
legacy_backup_timer_was_enabled=$(systemctl is-enabled codestra-backup.timer 2>/dev/null || true)
firewall_snapshot=
timers_enable_attempted=NO
legacy_backup_disabled=NO

rollback_activation() {
  local rc=$?
  set +e
  # A multi-unit enable can fail after enabling only a prefix. Disable every
  # candidate unconditionally whenever activation rolls back.
  systemctl disable --now "${periodic_timers[@]}" >/dev/null 2>&1 || true
  if [[ $legacy_backup_disabled == YES && $legacy_backup_timer_was_enabled == enabled ]]; then
    systemctl enable --now codestra-backup.timer >/dev/null 2>&1 || true
  fi
  if [[ -n $firewall_snapshot && -f $firewall_snapshot ]]; then
    python3 "$package_root/firewall/server-a-firewall.py" \
      --rollback "$firewall_snapshot" >/dev/null 2>&1 || true
  fi
  printf 'SERVER_A_CONTROLS_ACTIVATION=ROLLED_BACK_OR_FAIL_CLOSED\nTRANSACTION=%s\n' \
    "$transaction" >&2
  exit "$rc"
}
trap rollback_activation ERR

required_files=(
  "$config_root/database-backup.env"
  "$config_root/database-restore.env"
  "$config_root/centrifugo-probe.json"
  "$config_root/governance.env"
  "$config_root/runtime-policy.json"
  "$config_root/environment-isolation.json"
  "$config_root/database-security.json"
  "$config_root/realtime-ha.json"
  "$config_root/realtime-routing-evidence.json"
  "$config_root/odoo-copy-governance.json"
  "$config_root/redis-recovery.json"
  "$config_root/runtime-source-lock.json"
  "$config_root/firewall.json"
)
for path in "${required_files[@]}"; do
  [[ -f "$path" && ! -L "$path" ]] || {
    echo "required activation configuration is missing or is a symlink: $path" >&2
    exit 2
  }
  [[ $(stat -c '%u' "$path") -eq 0 ]] || {
    echo "activation configuration must be owned by root: $path" >&2
    exit 2
  }
  mode=$(stat -c '%a' "$path")
  (( (8#$mode & 0022) == 0 )) || {
    echo "activation configuration must not be group/other writable: $path" >&2
    exit 2
  }
done

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

assert_json() {
  local path=$1 pointer=$2 expected=$3
  python3 - "$path" "$pointer" "$expected" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1])
if not path.is_file() or path.is_symlink():
    raise SystemExit(f"missing or unsafe JSON evidence: {path}")
value=json.loads(path.read_text(encoding='utf-8'))
for token in sys.argv[2].strip('/').split('/') if sys.argv[2] != '/' else []:
    token=token.replace('~1','/').replace('~0','~')
    value=value[int(token)] if isinstance(value,list) else value[token]
try:
    wanted=json.loads(sys.argv[3])
except json.JSONDecodeError:
    wanted=sys.argv[3]
if value != wanted:
    raise SystemExit(
        f"evidence assertion failed: {path} {sys.argv[2]}={value!r}, expected {wanted!r}"
    )
PY
}

copy_pass_evidence() {
  local source=$1 destination=$2
  [[ -f "$source" && ! -L "$source" ]] || {
    echo "evidence is missing or is a symlink: $source" >&2
    return 1
  }
  [[ $(stat -c '%u' "$source") -eq 0 ]] || {
    echo "evidence is not owned by root: $source" >&2
    return 1
  }
  local evidence_mode
  evidence_mode=$(stat -c '%a' "$source")
  (( (8#$evidence_mode & 0022) == 0 )) || {
    echo "evidence is group/other writable: $source" >&2
    return 1
  }
  assert_json "$source" /status PASS
  install -m 0600 "$source" "$destination"
}

capture_ssh_state "$transaction/ssh-before.json"
python3 "$package_root/validate-source.py"

# The replacement backup must pass, upload off-host, and restore from that
# exact off-host object before the broken generated-name timer is retired.
systemctl start codestra-database-certification-backup.service
backup_stamp=$(cat "$backup_root/LAST_SUCCESS")
[[ $backup_stamp =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
  echo "new backup did not publish a valid success stamp" >&2
  exit 1
}
backup_status="$backup_root/$backup_stamp/STATUS.json"
for assertion in \
  /status=PASS \
  /encryption=PASS \
  /checksum=PASS \
  /off_host_copy=PASS \
  /immutable_retention=PASS
do
  assert_json "$backup_status" "${assertion%%=*}" "${assertion#*=}"
done
install -m 0600 "$backup_status" "$transaction/database-backup-status.json"

systemctl start codestra-database-certification-restore.service
restore_stamp=$(cat "$restore_root/LAST_SUCCESS")
[[ $restore_stamp =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
  echo "restore did not publish a valid success stamp" >&2
  exit 1
}
restore_status="$restore_root/$restore_stamp/RESTORE-RESULT.json"
for assertion in \
  /status=PASS \
  /source=OFF_HOST_ENCRYPTED_COPY \
  /gpg_signature=PASS \
  /keycloak_restored_startup/status=PASS \
  /n8n_credential_recovery/status=PASS \
  /restore_network_internal=true \
  /restore_public_ports=0
do
  assert_json "$restore_status" "${assertion%%=*}" "${assertion#*=}"
done
install -m 0600 "$restore_status" "$transaction/database-restore-result.json"

# Ten independent Centrifugo checks and three exact-SHA GitHub status
# publications/readbacks are retained, rather than trusting only the last file.
for index in $(seq -w 1 10); do
  systemctl start codestra-centrifugo-probe.service
  copy_pass_evidence \
    "$evidence_root/centrifugo/LAST_RESULT.json" \
    "$transaction/centrifugo/result-$index.json"
  sleep 1
done
for index in $(seq -w 1 3); do
  systemctl start codestra-financial-governance-publisher.service
  copy_pass_evidence \
    "$evidence_root/governance/LAST_RESULT.json" \
    "$transaction/governance/result-$index.json"
  assert_json "$transaction/governance/result-$index.json" /readback/state success
  sleep 1
done

# These audits are intentionally fail-closed. Server-side remediation of role,
# CONNECT, replica, Odoo-copy, resource, and isolation defects must happen first.
for unit in \
  codestra-database-security-audit.service \
  codestra-realtime-ha-audit.service \
  codestra-odoo-copy-governance-audit.service \
  codestra-redis-recovery-audit.service \
  codestra-runtime-source-lock-audit.service \
  codestra-container-policy-audit.service \
  codestra-environment-isolation-audit.service
do
  systemctl start "$unit"
done
copy_pass_evidence \
  "$evidence_root/database-security/LAST_RESULT.json" \
  "$transaction/database-security.json"
copy_pass_evidence \
  "$evidence_root/realtime-ha/LAST_RESULT.json" \
  "$transaction/realtime-ha.json"
copy_pass_evidence \
  "$evidence_root/odoo-copy-governance/LAST_RESULT.json" \
  "$transaction/odoo-copy-governance.json"
copy_pass_evidence \
  "$evidence_root/redis-recovery/LAST_RESULT.json" \
  "$transaction/redis-recovery.json"
copy_pass_evidence \
  "$evidence_root/runtime-source-lock/LAST_RESULT.json" \
  "$transaction/runtime-source-lock.json"
copy_pass_evidence \
  "$evidence_root/container-policy/LAST_RESULT.json" \
  "$transaction/container-policy.json"
copy_pass_evidence \
  "$evidence_root/environment-isolation/LAST_RESULT.json" \
  "$transaction/environment-isolation.json"
assert_json "$transaction/database-security.json" /normal_application_superusers 0
assert_json "$transaction/realtime-ha.json" /false_standby_removed true
assert_json "$transaction/odoo-copy-governance.json" /filestore_alignment true

python3 "$package_root/firewall/server-a-firewall.py" \
  --config "$config_root/firewall.json" \
  --evidence-root "$transaction/firewall" \
  --plan > "$transaction/firewall-plan.json"

if [[ ${CODESTRA_ACTIVATE_FIREWALL:-NO} != YES ]]; then
  echo "CODESTRA_ACTIVATE_FIREWALL must be YES for production perimeter activation" >&2
  exit 1
fi
[[ ${CODESTRA_OUT_OF_BAND_CONSOLE_CONFIRMED:-} == YES ]] || {
  echo "provider console proof is required" >&2
  exit 2
}
[[ ${CODESTRA_FIREWALL_APPLY_CONFIRM:-} == APPLY_SERVER_A_DEFAULT_DENY ]] || {
  echo "firewall confirmation is required" >&2
  exit 2
}
python3 "$package_root/firewall/server-a-firewall.py" \
  --config "$config_root/firewall.json" \
  --evidence-root "$transaction/firewall" \
  --apply > "$transaction/firewall-apply.json"
assert_json "$transaction/firewall/LAST_RESULT.json" /status PASS
assert_json "$transaction/firewall/LAST_RESULT.json" /host_ipv4_input_policy DROP
assert_json "$transaction/firewall/LAST_RESULT.json" /host_ipv6_input_policy DROP
firewall_snapshot=$(find "$transaction/firewall" -mindepth 2 -maxdepth 2 \
  -type f -name rollback-ruleset.nft | sort | tail -1)
[[ -n $firewall_snapshot && -f $firewall_snapshot ]] || {
  echo "firewall rollback snapshot was not preserved" >&2
  false
}

# Enable periodic controls only after all manual gates pass.
timers_enable_attempted=YES
systemctl enable --now "${periodic_timers[@]}"

# The old name-dependent backup is retired only after replacement backup,
# off-host restore, Keycloak startup, and n8n credential recovery pass.
systemctl disable --now codestra-backup.timer >/dev/null 2>&1 || true
if systemctl is-active --quiet codestra-backup.timer || systemctl is-enabled --quiet codestra-backup.timer 2>/dev/null; then
  echo "legacy generated-name backup timer did not stop and disable" >&2
  exit 1
fi
legacy_backup_disabled=YES

capture_ssh_state "$transaction/ssh-after.json"
assert_ssh_unchanged "$transaction/ssh-before.json" "$transaction/ssh-after.json"

installed_sha=$(basename "$current")
python3 - "$transaction" "$installed_sha" "$backup_stamp" "$restore_stamp" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1])
files=[]
for path in sorted(root.rglob('*')):
    if path.is_file() and path.name != 'ACTIVATION-RESULT.json':
        files.append({
            'path':str(path.relative_to(root)),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes':path.stat().st_size,
        })
payload={
  'schema':'codestra.server-a-controls-activation-result.v2',
  'status':'PASS',
  'timestamp':datetime.now(timezone.utc).isoformat(),
  'installed_commit':sys.argv[2],
  'backup_stamp':sys.argv[3],
  'restore_stamp':sys.argv[4],
  'new_timers_enabled':True,
  'legacy_backup_timer_disabled':True,
  'firewall_applied':True,
  'centrifugo_consecutive_successes':10,
  'governance_consecutive_successes':3,
  'database_security':'PASS',
  'realtime_ha':'PASS',
  'odoo_copy_governance':'PASS',
  'redis_recovery':'PASS',
  'runtime_source_lock':'PASS',
  'container_policy':'PASS',
  'environment_isolation':'PASS',
  'ssh_changed':False,
  'production_business_writes_executed':False,
  'live_provider_flags_changed':False,
  'evidence_files':files,
}
(root/'ACTIVATION-RESULT.json').write_text(
    json.dumps(payload,sort_keys=True,indent=2)+'\n'
)
PY
chmod 0600 "$transaction/ACTIVATION-RESULT.json"
trap - ERR
printf 'SERVER_A_REPOSITORY_CONTROLS_ACTIVATED=PASS\nINSTALLED_SHA=%s\nBACKUP_STAMP=%s\nRESTORE_STAMP=%s\nSSH_CHANGED=NO\nPRODUCTION_BUSINESS_WRITES_EXECUTED=NO\nEVIDENCE=%s\n' \
  "$installed_sha" "$backup_stamp" "$restore_stamp" "$transaction"
