#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo=$(cd "$root/../.." && pwd)
workflow="$repo/.github/workflows/ami-offhost-validation.yml"

python3 - "$workflow" "$root/compose.yaml" <<'PY'
import re, sys, yaml
from pathlib import Path
workflow_path, compose_path = map(Path, sys.argv[1:])
text = workflow_path.read_text(encoding="utf-8")
workflow = yaml.load(text, Loader=yaml.BaseLoader)
assert workflow["permissions"] == {"contents": "read"}
assert workflow["jobs"]["validate"]["runs-on"] == "ubuntu-24.04"
assert "pull_request" in workflow["on"]
assert "workflow_dispatch" in workflow["on"]
assert "pull_request_target" not in workflow["on"]
assert "environment" not in text
assert "secrets." not in text and "${{ secrets" not in text
uses = re.findall(r"^\s*uses:\s*([^#\s]+)", text, re.M)
assert uses
assert all(re.search(r"@[0-9a-f]{40}$", item) for item in uses), uses
compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
assert compose["networks"]["isolated"]["internal"] is True
svc = compose["services"]["asterisk"]
assert all(str(p).startswith("127.0.0.1:") for p in svc["ports"])
assert svc["cap_drop"] == ["ALL"]
assert sorted(svc["cap_add"]) == ["SETGID", "SETUID"]
assert "privileged" not in svc and "network_mode" not in svc
assert "/var/run/docker.sock" not in str(svc.get("volumes", []))
PY

if rg -n \
  '(pull_request_target|network_mode:[[:space:]]*host|/var/run/docker.sock|secrets\.|repository\.secrets|ssh[[:space:]])' \
  "$root/Dockerfile" "$root/compose.yaml" "$root/config" "$root/README.md" \
  "$root/scripts/container-entrypoint.sh" "$workflow"; then
  echo "forbidden off-host reference found" >&2
  exit 1
fi

for script in "$root"/scripts/*.sh; do bash -n "$script"; done
python3 -m compileall -q "$root/tests"
printf 'static off-host validation passed\n'
