#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
caddy fmt --diff "$ROOT/live/Caddyfile"
caddy validate --config "$ROOT/live/Caddyfile" --adapter caddyfile
caddy adapt --config "$ROOT/live/Caddyfile" --adapter caddyfile --validate >/dev/null
python3 "$ROOT/tests/test_authority.py"
echo CADDY_CONFIG_STRUCTURE=PASS
