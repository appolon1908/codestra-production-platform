#!/bin/sh
set -eu
umask 077

[ "$(id -u)" -eq 0 ] || { echo 'LAUNCH_RESULT=FAIL'; exit 2; }
[ "$#" -eq 0 ] || { echo 'LAUNCH_RESULT=FAIL'; exit 2; }
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
root=$(CDPATH='' cd -- "$script_dir/../.." && pwd -P)
record=$root/config/server-a-operator-installation-record.json
validator=$root/tools/validate_server_a_operator_installation_record.py
installer=$script_dir/install-server-a-operator.sh

for source in "$record" "$validator" "$installer"; do
  if [ ! -f "$source" ] || [ -L "$source" ]; then
    echo 'LAUNCH_RESULT=FAIL'
    exit 2
  fi
done
python3 "$validator" "$record" >/dev/null || { echo 'LAUNCH_RESULT=FAIL'; exit 2; }

python3 - "$record" "$installer" <<'PY'
import hashlib, json, pathlib, sys
record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
actual = hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest()
if actual != record["target_release"]["installer_sha256"]:
    raise SystemExit(2)
PY

public_key=$(python3 - "$record" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(r["arguments"]["operator_public_key"]["value"])
PY
)
expected_fingerprint=$(python3 - "$record" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(r["operator_public_key_fingerprint"]["value"])
PY
)
actual_fingerprint=$(ssh-keygen -lf "$public_key" -E sha256 | awk 'NR == 1 {print $2}')
[ "$actual_fingerprint" = "$expected_fingerprint" ] || { echo 'LAUNCH_RESULT=FAIL'; exit 2; }

record_value() {
  python3 - "$record" "$1" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(r["arguments"][sys.argv[2]]["value"])
PY
}
protected_sha=$(record_value protected_commit)
image_digest=$(record_value image_digest)
change_id=$(record_value change_id)
maintenance_date=$(record_value maintenance_date)
control_plane_archive_sha256=$(record_value control_plane_archive_sha256)
exec "$installer" --preserve-existing-sudoers \
  "$public_key" "$protected_sha" "$image_digest" "$change_id" \
  "$maintenance_date" "$control_plane_archive_sha256"
