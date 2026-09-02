# Call Follow-up Automation Outbox v1

## Boundary

```text
Odoo agent transaction
→ immutable Odoo outbox row
→ Odoo cron delivery worker
→ authenticated Codestra middleware endpoint
→ middleware outbox/router
→ n8n or approved downstream adapters
```

Odoo never calls n8n, VICIdial, PBX tables, or carrier APIs directly.

## Delivery

Each event uses:

- an exact-host allowlist;
- redirect rejection;
- Bearer API-key service identity;
- `Idempotency-Key`;
- `X-Event-Id`;
- `X-Correlation-Id`;
- `X-Tenant-Id`;
- `X-Timestamp`;
- `X-Signature: sha256=<HMAC>`.

The signature covers timestamp, event ID, tenant ID, and the exact canonical
JSON body. Each worker write is conditioned on the worker still owning the
current lease. Stale processing leases can be reclaimed without allowing an
older worker to overwrite the newer result.

Calendar mutation idempotency keys use the canonical payload hash rather than
a timestamp, preventing collisions when multiple reschedules occur inside the
same second.

## Manual retry

A manager may retry only `retry` or `dead` events. The lifetime attempt count is
preserved, the manual retry count is incremented, and a bounded three-attempt
budget is added. This preserves evidence while permitting a controlled retry.

## Fail-closed activation

Delivery defaults to disabled. Enable it only after the target URL, exact host
allowlist, tenant, Docker secret files, staging replay tests, dead-letter alerts,
backups, and rollback have been verified.

## Privacy

Payloads contain Odoo record identifiers and operational status only. Agent
notes, email bodies, recipient addresses, credentials, recordings, and raw
provider payloads are excluded.
