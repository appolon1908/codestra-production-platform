# Integration Testing

Run from the repository root:

```bash
PYTHONPATH=. /usr/bin/pytest-3 -q
AUDIT_SAFE_MODE=true ./scripts/full-connectivity-audit.sh
```

The audit defaults to safe mode, uses no production destination, redacts secrets by never reading their values, applies timeouts, and writes `artifacts/connectivity-audit.json`. A non-safe invocation is refused. Production checks require operator-approved secret-file references and must not be added to shell history.

Evidence on 2026-08-15: 189 passed, 3 skipped; the skipped tests require an explicitly supplied real NATS audit environment. Simulator/test IDs prove local Telnexa, Klyrow and Kyqra execution without external delivery.
