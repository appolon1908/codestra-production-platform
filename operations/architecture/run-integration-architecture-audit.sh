#!/bin/sh
set -eu

release_root=${CODESTRA_CONSTITUTION_ROOT:-/opt/codestra/integration-constitution/current}
state_dir=${CODESTRA_ARCHITECTURE_STATE_DIR:-/var/lib/codestra-integration-architecture}
textfile_dir=${CODESTRA_NODE_EXPORTER_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}

umask 077
install -d -m 0700 "$state_dir"
install -d -m 0755 "$textfile_dir"
snapshot_tmp=$(mktemp "$state_dir/runtime.XXXXXX")
evidence_tmp=$(mktemp "$state_dir/evidence.XXXXXX")
metric_tmp=$(mktemp "$textfile_dir/integration-architecture.prom.XXXXXX")
cleanup() { rm -f "$snapshot_tmp" "$evidence_tmp" "$metric_tmp"; }
trap cleanup EXIT INT TERM

python3 "$release_root/tools/capture_runtime_architecture.py" --output "$snapshot_tmp"
status=0
python3 "$release_root/tools/check_integration_architecture.py" \
  --root "$release_root" --runtime-snapshot "$snapshot_tmp" --evidence "$evidence_tmp" || status=$?
findings=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["critical_findings"]))' "$evidence_tmp")
printf '# HELP codestra_integration_architecture_critical_findings Critical fail-closed architecture findings.\n# TYPE codestra_integration_architecture_critical_findings gauge\ncodestra_integration_architecture_critical_findings %s\n' "$findings" > "$metric_tmp"
chmod 0644 "$metric_tmp"
mv -f "$metric_tmp" "$textfile_dir/integration-architecture.prom"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mv "$snapshot_tmp" "$state_dir/$stamp-runtime.json"
mv "$evidence_tmp" "$state_dir/$stamp-evidence.json"
trap - EXIT INT TERM
exit "$status"
