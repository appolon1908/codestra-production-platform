#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
container=$(docker compose -f "$root/compose.yaml" ps --quiet asterisk)
HARNESS_HOST=$(docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container")
export HARNESS_HOST
export HARNESS_PORT_OFFSET=-10000
python3 -m pytest -q "$root/tests/test_tls_validation.py"
