#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
docker compose -f "$root/compose.yaml" down --volumes --remove-orphans || true
if [[ -d "$root/runtime" ]]; then
  find "$root/runtime" -type f -delete
  find "$root/runtime" -depth -type d -empty -delete
fi
