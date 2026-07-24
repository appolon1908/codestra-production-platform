#!/usr/bin/env bash
set -euo pipefail

PACKAGE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$PACKAGE/../.." && pwd)

(
  cd "$PACKAGE"
  sha256sum --check SHA256SUMS
)
python3 "$ROOT/operations/monitoring/validate_phase5a.py"
python3 -m unittest discover -s "$ROOT/tests" -p 'test_monitoring_failure_handling.py'
python3 -m unittest discover -s "$ROOT/tests" -p 'test_operations.py'
echo "phase5a_evidence=PASS"
