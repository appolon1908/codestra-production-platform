#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT=${1:-"$ROOT/artifacts/connectivity-audit.json"}
mkdir -p "$(dirname "$OUTPUT")"
CONTROL_TMP=$(mktemp)
GATEWAY_TMP=$(mktemp)
trap 'rm -f "$CONTROL_TMP" "$GATEWAY_TMP"' EXIT
python3 "$ROOT/scripts/full_connectivity_audit.py" > "$CONTROL_TMP"
python3 "$ROOT/scripts/private_gateway_audit.py" > "$GATEWAY_TMP"
python3 - "$CONTROL_TMP" "$GATEWAY_TMP" "$OUTPUT" <<'PY'
import json, sys
control=json.load(open(sys.argv[1],encoding="utf-8")); gateway=json.load(open(sys.argv[2],encoding="utf-8"))
value={"schema_version":"full-connectivity-audit.v1","safe_mode":True,"real_bulk_sms_or_email_sent":False,"control_plane":control,"private_gateway":gateway,"tests":control["tests"]+gateway["tests"]}
value["summary"]={"pass":sum(x["status"]=="PASS" for x in value["tests"]),"fail":sum(x["status"]=="FAIL" for x in value["tests"])}
value["run_id"]=control["run_id"]
json.dump(value,open(sys.argv[3],"w",encoding="utf-8"),indent=2,sort_keys=True); open(sys.argv[3],"a").write("\n")
PY
python3 -m json.tool "$OUTPUT" >/dev/null
printf 'Connectivity audit evidence: %s\n' "$OUTPUT"
python3 - "$OUTPUT" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
print("PASS={pass} FAIL={fail} RUN={run_id}".format(**value["summary"], run_id=value["run_id"]))
raise SystemExit(1 if value["summary"]["fail"] else 0)
PY
