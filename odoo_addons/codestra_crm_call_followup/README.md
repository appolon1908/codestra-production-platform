# Codestra CRM Call Follow-up — Odoo 19

A production-oriented Odoo 19 addon for completing the CRM workflow immediately after a call.

## User flow

1. The telephony middleware reports a completed call through authenticated Odoo RPC.
2. Odoo creates one immutable, company-scoped call event and sends a bus notification to the assigned agent.
3. The agent receives a modern modal containing:
   - structured call outcome;
   - rich-text notes;
   - callback or appointment calendar picker;
   - duration and reminder controls;
   - editable professional follow-up email.
4. Saving a callback or appointment creates or updates an Odoo calendar event.
5. The agent receives Odoo's native in-app calendar preparation popup 30 minutes before the event.
6. When enabled, the linked client and assigned agent are calendar attendees and each receives the email reminder 15 minutes before the event.
7. The CRM opportunity records the completed follow-up in its chatter and exposes call history through a smart button.

Closing the modal without completing it does not discard the action. Pending records are reloaded when the agent returns to the Odoo backend.

## Security and reliability

- No public HTTP controller is exposed.
- Only a dedicated Odoo API-key user assigned to `Call Follow-up / Integration Service` may invoke `register_completed_call`.
- Human users cannot create or delete call-event records.
- Agents can read and update only their assigned records in their allowed companies.
- Managers can review company records but cannot erase the audit trail.
- External `event_id` is protected by a database unique constraint scoped by company.
- Concurrent duplicate events are handled inside a PostgreSQL savepoint and return the original record.
- The middleware is the telephony gateway. This addon contains no direct VICIdial, carrier, or PBX write path.
- Immediate emails are queued through Odoo mail; the request does not force SMTP delivery inside the user transaction.
- Calendar changes synchronize back to the CRM follow-up record.

## Required Odoo applications

- CRM
- Calendar
- Discuss / Mail
- Bus
- Web

The module version is `19.0.1.0.0` and is intended for Odoo 19 only.

## Installation

```bash
./odoo-bin \
  -d <staging_database> \
  --addons-path=<odoo_addons>,odoo/addons \
  -i codestra_crm_call_followup \
  --stop-after-init
```

Run the module tests in a disposable staging database:

```bash
./odoo-bin \
  -d <test_database> \
  --addons-path=<odoo_addons>,odoo/addons \
  -i codestra_crm_call_followup \
  --test-enable \
  --test-tags /codestra_crm_call_followup \
  --stop-after-init
```

Run the repository gate:

```bash
python scripts/validate_odoo_crm_call_followup.py
```

## Integration contract

Call the public model method through authenticated Odoo RPC:

- Model: `codestra.crm.call.followup`
- Method: `register_completed_call`
- Positional arguments: one payload dictionary
- Authentication: dedicated Odoo user plus API key
- Required group: `codestra_crm_call_followup.group_call_followup_service`

Example payload:

```json
{
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
  "duration_seconds": 380
}
```

Successful first delivery:

```json
{
  "followup_id": 1204,
  "event_id": "vicidial-call-ended-01J7F6XQH2",
  "state": "pending",
  "replayed": false
}
```

A retry with the same `company_id` and `event_id` returns the same `followup_id` with `replayed: true` and does not issue a second popup.

## Configuration checklist

- Assign normal agents to `Call Follow-up / Agent`.
- Assign supervisors to `Call Follow-up / Manager`.
- Create one non-human Odoo service user for middleware RPC and assign only `Call Follow-up / Integration Service` plus required company access.
- Store its API key in the middleware secret store; never commit it.
- Confirm long-polling/websocket bus traffic reaches the Odoo workers.
- Configure and test an outgoing mail server and Odoo mail queue cron.
- Link CRM leads to contacts with valid email addresses when 15-minute client reminders are required.
- Ensure each agent has a valid email address and time zone.

## Release acceptance

A production release is blocked until all of the following evidence is attached to the pull request:

- clean install on a disposable Odoo 19 database;
- upgrade on a sanitized staging copy;
- module tests passing;
- duplicate-event replay test passing;
- browser post-call popup verified for the assigned agent only;
- callback creation, reschedule, cancellation, and calendar synchronization verified;
- 30-minute Odoo notification verified;
- 15-minute email delivered to both client and agent in a mail-capture environment;
- immediate email queued with the reviewed sender identity;
- multi-company isolation verified;
- database backup and tested rollback procedure recorded.

Do not merge or deploy based only on static validation.
