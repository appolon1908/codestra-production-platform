# Call Follow-up Automation Outbox v1

## Boundary

```text
Odoo agent transaction
→ immutable Odoo outbox row
→ Odoo cron delivery worker
→ authenticated Codestra middleware `/api/v1/events/odoo`
→ middleware outbox/router
→ n8n or approved downstream adapters
```

Odoo never calls n8n, VICIdial, PBX tables, or carrier APIs directly.

## Event namespace

The outbox may keep its internal business labels, but every middleware envelope
uses the single approved Odoo namespace:

```text
call_followup.completed
call_followup.callback_scheduled
call_followup.appointment_scheduled
call_followup.email_queued
call_followup.calendar_rescheduled
call_followup.calendar_cancelled
```

The middleware registers only the `call_followup.*` prefix for this capability.
Legacy `post_call.*`, `callback.*`, `appointment.*`, and `calendar.*` values are
not valid Odoo ingress event types.

## Delivery identity

Each request carries two different identities:

- `metadata.logical_event_id` is the immutable Odoo outbox event UUID.
- `event_id` and `X-Event-Id` are the deterministic transport nonce for the
  current durable attempt.

A reclaimed worker repeats the same transport nonce for the same unrecorded
attempt. Once a failed attempt is durably recorded, the next attempt uses a new
transport nonce while retaining the same producer content and
`Idempotency-Key`.

Mutable attempt counters are never included in the signed envelope. This keeps
producer content stable for middleware idempotency comparison.

## Authentication

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

The signature covers, in order, timestamp, transport event ID, the exact source
string `odoo`, and the canonical JSON body. This exactly matches the middleware
ingress verifier.

## Receipts and replay reconciliation

A 202 receipt is accepted only when it identifies the current transport nonce,
the expected correlation ID, `duplicate=false`, a known middleware state, and
no provider projection.

A 200 duplicate receipt is accepted only when it identifies a deterministic
transport nonce from the current or an earlier durable attempt, preserves the
expected correlation ID, sets `duplicate=true`, reports a known middleware
state, and has no provider projection.

A 409 response is successful reconciliation only when it is the exact
middleware receipt:

```json
{
  "error": "replayed_event_id",
  "event_id": "<current-transport-nonce>",
  "projection": null
}
```

Any malformed, mismatched, oversized, or non-JSON receipt fails closed.
Ordinary 4xx responses remain permanent failures except the existing 408/429
retry policy. Transport errors retain the row for bounded retry.

## Worker fencing

Each worker write is conditioned on the worker still owning the current lease.
Stale processing leases can be reclaimed without allowing an older worker to
overwrite the newer result.

Calendar mutation idempotency keys use the canonical payload hash rather than
a timestamp, preventing collisions when multiple reschedules occur inside the
same second.

## Manual retry

A manager may retry only `retry` or `dead` events. The lifetime attempt count is
preserved, the manual retry count is incremented, and a bounded three-attempt
budget is added. This preserves evidence while permitting a controlled retry.

## Fail-closed activation

Delivery defaults to disabled. Enable it only after the target URL, exact host
allowlist, tenant, Docker secret files, staging replay tests, dead-letter
alerts, backups, rollback rehearsal, and middleware readback have been
verified.

## Privacy

Payloads contain Odoo record identifiers and operational status only. Agent
notes, email bodies, recipient addresses, credentials, recordings, and raw
provider payloads are excluded.
