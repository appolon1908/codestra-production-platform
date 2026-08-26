# Klyrow email status downstream

Klyrow status callbacks traverse the authenticated private gateway into the
control-plane durable event ledger, then fan out to authenticated n8n and Odoo
adapters. This path never creates or sends email.

Supported status types are `klyrow.email.delivered`,
`klyrow.email.bounced`, and `klyrow.email.deferred`. The private gateway's
`klyrow.email.event` transport wrapper is normalized from
`payload.event_type`; the original wrapper is retained in
`metadata.transport_event_type`. The envelope preserves `event_id`,
`correlation_id`, `message_id`, tenant/customer identity, provider, and
`occurred_at`.

Middleware to n8n uses a dedicated bearer credential plus an HMAC signature.
The active endpoints are `codestra-email-delivered`,
`codestra-email-bounced`, and `codestra-email-deferred`. Middleware to Odoo
uses a tenant allowlist and HMAC over timestamp, event ID, HTTP method, path,
and body. Secrets remain outside Git.

Odoo records immutable rows in `codestra.email.delivery.status`:

- status field: `status`
- correlation field: `correlation_id`
- message ID field: `message_id`
- event ID field: `event_id` (unique)

Retries use bounded exponential backoff with five attempts by default and a
terminal durable `dead_letter` state. The authenticated operations replay API
re-drives the complete downstream fan-out, resets the attempt budget, and
audits the action. n8n deduplicates by tenant/idempotency key; Odoo deduplicates
by immutable event ID and returns the prior result for an identical replay.

Synthetic evidence captured 2026-08-16:

- Delivered event `klyrow-synthetic-event-741589cc-192e-4225-a8ac-d5d186bfc682`
  reached n8n execution `117` successfully with correlation
  `klyrow-synthetic-e2e-9e0c9532-8380-454e-a08a-d993716b7145`, then created
  Odoo status record `3`. A later exact replay produced n8n execution `118`
  and left exactly one Odoo record.
- Bounce event `klyrow-synthetic-bounce-cfef8d892b094abd97d6c1dccc3aeaeb`
  reached n8n execution `119` and Odoo record `4` with status `bounced`.
- No SMTP transaction or email creation occurred. `ALLOW_LIVE_EMAIL=false`
  remained unchanged; Klyrow safe mode and the production gate were not
  modified.
