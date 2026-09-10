# Realtime authority

This document is the release authority for realtime delivery. A deployment must
not substitute Odoo bus, a browser tab, Redis, or an independently writable
gateway database for the responsibilities assigned here.

## Ownership

| Concern | Authority | Required behavior |
| --- | --- | --- |
| Telephony event creation and business/campaign scope | Codestra middleware | Creates the versioned event after validating the authoritative mapping. |
| WebSocket session, ticket, replay, and scoped delivery | `websocket_gateway` | Persists accepted events, enforces tenant/business-unit/agent/campaign scope, and permits no browser commands. |
| Durable post-call workflow record | Odoo `codestra_crm_call_followup` | Owns completion, snooze, callback, email, calendar, and audit state. |
| Popup ownership | Odoo `codestra_crm_call_followup_realtime` | Atomically grants one expiring PostgreSQL-backed lease to one assigned-agent browser tab. |
| Popup notification hint | Odoo bus | May wake a browser so it attempts a claim; it is not durable state or ownership authority. |
| Browser | None | Presents data and holds an opaque, expiring lease token only. |
| Redis | None for durable realtime state | May be used for reconstructible coordination or caching only. |

## Required flow

```text
VICIdial adapter/event ingestion
  -> authenticated middleware validation and normalization
  -> POST /internal/v1/realtime/events
  -> WebSocket gateway persistence and scoped delivery
  -> browser receives a notification

Completed call workflow
  -> middleware registers the idempotent completed call in Odoo
  -> Odoo creates or returns the durable follow-up record
  -> Odoo bus may notify the assigned agent
  -> browser atomically claims the record through the Odoo lease API
  -> Odoo remains authoritative for completion and lease cleanup
```

The two flows meet at the same business event but do not share authority. The
WebSocket gateway never mutates Odoo workflow state. Odoo bus never replaces the
gateway for telephony event delivery or replay.

## Accepted implementation

- Gateway source: `websocket_gateway/` from the immutable 6101 release.
- Popup coordination: `models/realtime_lease.py` and
  `static/src/js/post_call_lease_service.js`.
- HA: one writable PostgreSQL authority. Promotion requires fencing the former
  primary, verified replication state, and the fail-closed runbook.

The alternative `realtime.py`, `realtime_api.py`, and
`post_call_realtime_service.js` implementation is not part of this release and
must not be added alongside the accepted lease protocol.

## Activation gates

Production remains blocked unless all of the following have evidence:

1. Exact gateway image digest and source SHA are signed and recorded.
2. Gateway migration head is verified before readiness.
3. Cross-scope, replay, duplicate-ticket, and backpressure tests pass.
4. Two browser tabs race for one follow-up and exactly one lease is granted.
5. Expiry, renewal, release, completion, snooze, and reconnect recovery pass.
6. The standby is read-only and the former primary can be fenced before promotion.
7. Public routing, monitoring, rollback, and a synthetic WSS session pass.

No failed gate may be waived by changing a test, disabling readiness, routing
around middleware, or enabling a second writable authority.
