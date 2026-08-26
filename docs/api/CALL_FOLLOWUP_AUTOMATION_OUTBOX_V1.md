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

- Bearer API-key service identity;
- `Idempotency-Key`;
- `X-Event-Id`;
- `X-Correlation-Id`;
- `X-Tenant-Id`;
- `X-Timestamp`;
- `X-Signature: sha256=<HMAC>`.

The signature covers timestamp, event ID, tenant ID, and the exact canonical
JSON body.

## Fail-closed activation

Delivery defaults to disabled. Enable it only after the target URL, tenant,
Docker secret files, staging replay tests, dead-letter alerts, backups, and
rollback have been verified.

## Privacy

Payloads contain Odoo record identifiers and operational status only. Agent
notes, email bodies, recipient addresses, credentials, recordings, and raw
provider payloads are excluded.
