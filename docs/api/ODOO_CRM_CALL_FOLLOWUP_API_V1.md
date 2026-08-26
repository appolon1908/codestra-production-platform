# Odoo CRM Call Follow-up RPC API v1

## Purpose

This contract accepts authoritative `call.completed` events from Codestra middleware and creates one pending Odoo post-call action for the assigned CRM agent.

The endpoint is **not** a public HTTP controller. The caller authenticates through Odoo JSON-RPC/XML-RPC with a dedicated non-human user and API key. That user must belong to:

```text
codestra_crm_call_followup.group_call_followup_service
```

Odoo, n8n, browser clients, and agents must never write directly to VICIdial, a PBX, DIDWW, Twilio, or another carrier. Middleware remains the telephony authority.

## Models and methods

Preferred versioned API model:

```text
model: codestra.crm.call.followup.api
method: health
args: []
```

```text
model: codestra.crm.call.followup.api
method: get_contract
args: []
```

```text
model: codestra.crm.call.followup.api
method: register_completed_call
args: [payload]
```

Backward-compatible model methods remain available:

```text
codestra.crm.call.followup.get_api_health()
codestra.crm.call.followup.get_api_contract()
codestra.crm.call.followup.register_completed_call(payload)
```

They delegate to the versioned API model and must not contain independent business logic.

## Request

The canonical request schema is:

```text
odoo_addons/codestra_crm_call_followup/contracts/completed_call.v1.schema.json
```

Example:

```json
{
  "api_version": "1.0",
  "event_id": "vicidial-call-ended-01J7F6XQH2",
  "correlation_id": "01J7F6XQH2",
  "call_id": "M123456789",
  "source": "codestra-middleware",
  "company_id": 1,
  "agent_user_id": 42,
  "lead_id": 901,
  "partner_id": 455,
  "started_at": "2026-08-26 14:00:00",
  "ended_at": "2026-08-26 14:06:20",
  "duration_seconds": 380,
  "call_direction": "outbound",
  "metadata": {
    "campaign_key": "transportation-sales"
  }
}
```

Exactly one of `agent_user_id` or `agent_login` must be supplied.

`ended_at` is required. `started_at` is optional; when it is missing and `duration_seconds` is positive, Odoo derives the start time from the end time and duration.

Unknown top-level fields fail closed. Provider-specific values belong in `metadata`; do not add new top-level keys without publishing a new reviewed contract.

## Response

The canonical response schema is:

```text
odoo_addons/codestra_crm_call_followup/contracts/completed_call.response.v1.schema.json
```

First accepted delivery:

```json
{
  "api_version": "1.0",
  "status": "accepted",
  "created": true,
  "replayed": false,
  "followup_id": 1204,
  "event_id": "vicidial-call-ended-01J7F6XQH2",
  "correlation_id": "01J7F6XQH2",
  "state": "pending",
  "next_action": "post_call_popup"
}
```

Idempotent replay:

```json
{
  "api_version": "1.0",
  "status": "accepted",
  "created": false,
  "replayed": true,
  "followup_id": 1204,
  "event_id": "vicidial-call-ended-01J7F6XQH2",
  "correlation_id": "01J7F6XQH2",
  "state": "pending",
  "next_action": "post_call_popup"
}
```

## Idempotency

The idempotency scope is:

```text
(company_id, event_id)
```

The first accepted request stores a SHA-256 fingerprint of immutable call identity fields.

A retry with the same scope and the same immutable values returns the existing record with `replayed=true`.

A retry with the same scope but different immutable values fails with:

```text
IDEMPOTENCY_CONFLICT
```

Middleware must treat that response as an operational exception. It must not generate a new event ID to bypass the conflict.

## Validation and error classes

Odoo raises `AccessError` or `ValidationError`. Middleware must map the message prefix to an operational error code without exposing credentials or customer email bodies in logs.

Stable prefixes include:

```text
UNSUPPORTED_API_VERSION
UNKNOWN_PAYLOAD_FIELDS
PAYLOAD_TOO_LARGE
IDEMPOTENCY_CONFLICT
```

Other validation failures include missing or invalid company, agent, lead, partner, timeline, duration, and cross-company references.

Authorization failures are not retryable until identity or company assignment is corrected.

Validation and idempotency conflicts are not retryable with the same invalid payload.

Transport timeouts and temporary Odoo unavailability are retryable with the **same** `event_id`.

## Middleware retry behavior

1. Persist the authoritative completed-call event before calling Odoo.
2. Send one request with a deterministic event ID.
3. Use a bounded timeout.
4. Retry timeouts and transient 5xx responses with exponential backoff and jitter.
5. Reuse the original event ID and immutable payload on every retry.
6. Validate the complete response schema.
7. Acknowledge the source event only after a valid accepted response or durable dead-letter retention.
8. Record success, replay, authorization failure, validation failure, conflict, timeout, and dead-letter metrics.
9. Never log API keys, full email bodies, recordings, or unrestricted customer data.

## Health and readiness

`health()` verifies the authenticated service identity and returns the API version and server time. It does not prove database migrations, bus delivery, browser rendering, mail delivery, or calendar cron execution.

Readiness for production additionally requires:

- clean addon install and upgrade on Odoo 19;
- assigned-agent bus popup;
- concurrent duplicate replay;
- conflicting replay rejection;
- multi-company isolation;
- mail queue and retry evidence;
- 30-minute in-app reminder;
- 15-minute client and agent reminders;
- paired database/filestore backup;
- rollback rehearsal;
- independent approval of the exact final SHA.
