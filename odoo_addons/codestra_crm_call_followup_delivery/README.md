# Codestra CRM Call Follow-up Delivery Outbox

Optional Odoo 19 extension that adds an immutable operational ledger around immediate post-call email while retaining Odoo's native retryable `mail.mail` queue.

## What it adds

- deterministic delivery idempotency key per company, call follow-up, kind, and recipient hash;
- retained Odoo mail records (`auto_delete=False`) for delivery evidence;
- queued, sent, retry-scheduled, dead-letter, and cancelled states;
- bounded five-attempt retry budget;
- exponential retry delays of 1, 5, 15, 60, and 360 minutes;
- `FOR UPDATE SKIP LOCKED` retry worker selection;
- reconciliation against Odoo mail states;
- manager-only **Retry Now**, **Cancel Delivery**, **Open Call Follow-up**, and **Open Odoo Mail** actions;
- assigned-agent and company-scoped read access;
- immutable delivery audit records.

The extension does not send SMTP synchronously from the post-call popup. The popup creates a queued Odoo mail and a delivery ledger row in the same database transaction. Odoo's mail queue performs external delivery.

## Cron jobs

```text
CRM Call Follow-up: Reconcile email delivery — every 2 minutes
CRM Call Follow-up: Retry failed email delivery — every 1 minute
```

## Safety

- No direct Postal, Klyrow, SMTP-provider, VICIdial, PBX, carrier, or n8n call.
- No credentials in Odoo records or Git.
- Email body access is limited by assigned-agent and company rules.
- Delivery records cannot be deleted.
- Sent records cannot be retried or cancelled.

## Required runtime evidence

- queued email creates exactly one delivery ledger row;
- successful Odoo mail changes delivery to sent;
- synthetic SMTP exception schedules a retry;
- retry returns the existing mail to outgoing state without a duplicate ledger row;
- fifth failed attempt becomes dead letter;
- manager recovery actions work;
- another agent/company cannot see the record;
- mail server outage does not roll back completed CRM notes, disposition, or calendar state;
- no customer data appears in unrestricted logs or metrics.
