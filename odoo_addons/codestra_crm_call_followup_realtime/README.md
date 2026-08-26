# Codestra CRM Call Follow-up Realtime — Odoo 19

This optional addon installs on top of `codestra_crm_call_followup` and replaces the basic browser popup service with a server-authoritative lease protocol.

## Why this is separate

Realtime delivery changes browser behavior, Odoo bus handling, scheduled recovery, and supervisor operations. Keeping it in its own addon and branch allows the core CRM workflow to be installed or rolled back independently.

## Runtime flow

1. Middleware registers the completed call through the core versioned RPC API.
2. Odoo sends the assigned agent a bus event.
3. The browser requests a 90-second server-side claim.
4. Only the assigned agent and one browser client can hold the claim.
5. The browser renews the claim every 45 seconds while the modal is open.
6. Closing, completing, navigating away, or failing releases the claim; an abandoned claim expires automatically.
7. Browser reconnect recovery returns only available or expired pending actions.
8. The supervisor queue shows pending, claimed, expired, and repeatedly delivered records.

## RPC model

`codestra.crm.call.followup.realtime.api`

Methods:

- `capabilities_v1()`
- `claim_v1(followup_id, client_id, lease_seconds=90)`
- `acknowledge_opened_v1(followup_id, claim_token)`
- `renew_v1(followup_id, claim_token, lease_seconds=90)`
- `release_v1(followup_id, claim_token, reason="closed")`
- `recover_v1(client_id, limit=10)`

These methods are for authenticated Odoo browser sessions. They do not expose a public controller and do not perform telephony writes.

## Required acceptance evidence

- two tabs receive one effective modal;
- a second browser returns `busy` while the lease is active;
- heartbeat renewal prevents premature redelivery;
- closing the modal releases the action;
- losing the browser causes server-side expiry and redelivery;
- only the assigned agent can claim or recover the record;
- managers can inspect the queue but do not take agent ownership;
- websocket/long-polling interruption does not lose the action;
- no duplicate email, chatter entry, calendar event, or completion occurs.

Production deployment remains blocked until the exact branch SHA passes disposable Odoo 19 tests, browser tests, staging tests, and independent review.
