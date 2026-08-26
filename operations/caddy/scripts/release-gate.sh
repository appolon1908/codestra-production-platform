#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/validate.sh"
bash -n "$ROOT"/scripts/*.sh
python3 "$ROOT/tests/test_authority.py"
if command -v gitleaks >/dev/null; then gitleaks detect --source "$ROOT" --no-git --no-banner --redact; fi
find "$ROOT" -type f -perm /0022 -print -quit | grep -q . && { echo writable_package_file >&2; exit 2; } || true
echo CADDY_RELEASE_GATES=PASS
