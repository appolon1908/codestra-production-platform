#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
"$root/scripts/generate-test-pki.sh"
docker compose -f "$root/compose.yaml" build --pull=false
docker compose -f "$root/compose.yaml" up --detach --wait
docker image inspect --format='{{.Id}}' codestra/asterisk18-offhost:18.26.4 > "$root/runtime/image-digest.txt"
