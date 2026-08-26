#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/validate.sh"
bash -n "$ROOT"/scripts/*.sh
python3 "$ROOT/tests/test_authority.py"
if [ -S /run/caddy/admin.sock ] && curl -fsS --max-time 3 http://127.0.0.1:8001/status >/dev/null; then
  "$ROOT/scripts/audit-endpoints.sh"
fi
if command -v gitleaks >/dev/null; then gitleaks detect --source "$ROOT" --no-git --no-banner --redact; fi
find "$ROOT" -type f -perm /0022 -print -quit | grep -q . && { echo writable_package_file >&2; exit 2; } || true
echo CADDY_RELEASE_GATES=PASS
