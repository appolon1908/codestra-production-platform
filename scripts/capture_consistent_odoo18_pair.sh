#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' 'DEPRECATED: capture_consistent_odoo18_pair.sh now delegates to capture_consistent_odoo19_pair.sh' >&2
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$SCRIPT_DIR/capture_consistent_odoo19_pair.sh" "$@"
