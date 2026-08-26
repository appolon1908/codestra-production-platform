# Codestra CRM Call Follow-up — Odoo 19

A production-oriented Odoo 19 addon that turns every authoritative completed-call event into a structured CRM action for the assigned agent.

## Agent workflow

1. Codestra middleware reports `call.completed` through authenticated Odoo RPC.
2. Odoo creates one immutable, company-scoped call record and sends a bus message to the assigned agent.
3. The agent receives a responsive post-call form with:
   - final disposition;
   - priority and customer sentiment;
   - rich-text notes;
   - callback or appointment date, duration, channel, link, or location;
   - editable immediate follow-up email;
   - clear **Save & Complete**, **Save & Schedule**, **Complete Without Email**, **Save & Remind Me in 10 Minutes**, and **Open CRM** actions.
4. Scheduling creates or updates a private Odoo calendar event linked to the call.
5. The assigned agent receives an in-app preparation popup 30 minutes before the event.
6. When enabled, the linked client and assigned agent each receive an email reminder 15 minutes before the event.
7. The CRM lead records the outcome, priority, sentiment, next step, compliance flag, and notes in its chatter.
8. CRM smart buttons expose complete call history and pending call actions.

Closing the form does not erase the task. Snooze saves the draft and hides it for ten minutes; browser reconnect recovers eligible unfinished actions.

## Core reliability

- No public HTTP controller.
- Dedicated API-key service identity and service-only RPC methods.
- Published request/response JSON Schemas.
- Versioned RPC model plus backward-compatible delegates.
- 64 KiB payload bound and unknown-field rejection.
- Company/agent/lead/customer isolation.
- Agent must be active, internal, company-authorized, and enabled for the feature.
- Database uniqueness on `(company_id, event_id)`.
- SHA-256 fingerprint for immutable event material.
- Conflicting replay fails closed with `IDEMPOTENCY_CONFLICT`.
- PostgreSQL row lock prevents duplicate completion side effects.
- Completed-call records cannot be manually created or deleted.
- Immediate mail is queued through Odoo; SMTP is not forced inside the agent transaction.
- Calendar reschedule, location change, archive, and deletion synchronize back to the follow-up.
- Do-not-call and wrong-number results require notes, disable automatic schedule/email, and flag compliance review.
- No direct VICIdial, PBX, DIDWW, Twilio, carrier, Postal, or database-table write path.

## API

Preferred model:

```text
codestra.crm.call.followup.api
```

Methods:

```text
health()
get_contract()
register_completed_call(payload)
```

Compatibility methods remain on:

```text
codestra.crm.call.followup
```

See:

```text
docs/api/ODOO_CRM_CALL_FOLLOWUP_API_V1.md
odoo_addons/codestra_crm_call_followup/contracts/completed_call.v1.schema.json
odoo_addons/codestra_crm_call_followup/contracts/completed_call.response.v1.schema.json
```

Example request:

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
  "call_direction": "outbound"
}
```

Example response:

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

## Required Odoo applications

- CRM
- Calendar
- Discuss / Mail
- Bus
- Web

The module version is `19.0.2.0.0` and targets Odoo 19 only.

## Static and disposable tests

```bash
python scripts/validate_odoo_crm_call_followup.py
```

```bash
./scripts/test_odoo_crm_call_followup_disposable.sh
```

A static pass does not prove browser bus delivery, cron execution, SMTP delivery, database migration safety, backup integrity, or rollback.

## Branch ownership

Heavy capabilities are stacked separately:

```text
docs/architecture/ODOO_CRM_CALL_FOLLOWUP_BRANCH_MAP.md
```

Realtime leases, delivery outbox, supervisor analytics, and Docker release authority must remain in their own branches and pull requests.

## Production gate

Do not merge or deploy until the exact final SHA has:

- clean Odoo 19 install and upgrade;
- addon tests;
- sequential and concurrent idempotency;
- conflicting replay rejection;
- assigned-agent popup and reconnect recovery;
- multi-company isolation;
- callback create/reschedule/cancel/location synchronization;
- 30-minute in-app notification;
- 15-minute client and agent mail-capture evidence;
- immediate email queue/retry evidence;
- paired database and filestore backup;
- rollback rehearsal;
- protected checks;
- fresh independent approval.
