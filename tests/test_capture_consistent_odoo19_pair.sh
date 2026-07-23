#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
IMPL="$ROOT/scripts/capture_consistent_odoo19_pair.sh"
ALIAS="$ROOT/scripts/capture_consistent_odoo18_pair.sh"

bash -n "$IMPL" "$ALIAS"
test -x "$IMPL"
test -x "$ALIAS"
grep -q 'DEPRECATED:' "$ALIAS"
grep -q 'capture_consistent_odoo19_pair.sh' "$ALIAS"
! grep -Eq 'Config\.Env|\.Config\.Env|containers\.before\.json' "$IMPL"
grep -q 'containers.before.txt' "$IMPL"
grep -q 'docker inspect -f' "$IMPL"

printf '%s\n' 'CAPTURE_SCRIPT_REGRESSION=PASS'
