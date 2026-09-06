# Odoo CRM Call Follow-up RPC v1

## Purpose

This contract accepts authoritative completed-call events from Codestra
middleware and creates one pending Odoo CRM follow-up for the assigned agent.

The integration path is:

```text
telephony provider or VICIdial
→ restricted adapter
→ Codestra middleware
→ authenticated Odoo RPC
→ codestra.crm.call.followup.register_completed_call_v1
```

Odoo and n8n must not write directly to VICIdial, PBX tables, or carrier APIs.

## Authentication

Use a non-human Odoo user with an API key and only the required company access
plus `codestra_crm_call_followup.group_call_followup_service`.

## Request

Call model `codestra.crm.call.followup`, method
`register_completed_call_v1`, with one object matching
`api/completed_call_v1.schema.json`.

`event_id`, `company_id`, `ended_at`, and one of `agent_user_id` or
`agent_login` are required.

## Idempotency

The idempotency scope is `(company_id, event_id)`.

- Same key and same immutable payload: accepted as `replayed=true`.
- Same key and different immutable payload: rejected.
- A retry may use a different `correlation_id`; correlation metadata is excluded
  from the immutable fingerprint.

## Success response

```json
{
  "api_version": "1.0",
  "accepted": true,
  "followup_id": 123,
  "event_id": "vicidial-20260826-0001",
  "company_id": 1,
  "state": "pending",
  "replayed": false,
  "correlation_id": "trace-123",
  "call_id": "call-456",
  "request_fingerprint": "sha256-hex"
}
```

## Reconciliation

Call `get_completed_call_status_v1(company_id, event_id)` after uncertain network
outcomes. Never generate a new `event_id` merely because the client timed out.

## Retry policy

Use bounded exponential backoff with jitter. Retain the event durably until Odoo
returns a valid success response or the event is moved to an operational
dead-letter queue. Never log API keys or full email bodies.
