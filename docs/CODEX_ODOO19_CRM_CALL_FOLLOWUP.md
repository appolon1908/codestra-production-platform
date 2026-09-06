# Codex Directive — Odoo 19 CRM Call Follow-up

## Scope

Implement, validate, integrate, and release the addon on this feature branch only:

```text
repository: appolon1908-hue/codestra-production-platform
base: release/production-activation
feature branch: feature/odoo19-crm-call-followup-final-20260826
addon: odoo_addons/codestra_crm_call_followup
Odoo target: 19
```

Read `AGENTS.md`, `CODEX_APP_SERVER_A.md`, and the addon `README.md` before changing files. Those controls remain authoritative.

## Non-negotiable architecture

1. Odoo and n8n must never write directly to VICIdial, a carrier, or a PBX.
2. The existing middleware remains the telephony gateway and the only producer of completed-call events.
3. The middleware must call Odoo with a non-human API-key identity assigned to `codestra_crm_call_followup.group_call_followup_service`.
4. Do not add a public, anonymous, or shared-secret HTTP controller to this addon.
5. Preserve the unique `(company_id, event_id)` constraint and database race handling.
6. Preserve multi-company and assigned-agent record rules.
7. Never commit API keys, SMTP credentials, database credentials, customer data, recordings, or production dumps.
8. Keep every live-write and production-dialing gate disabled unless the approved production change explicitly authorizes it. This addon does not require direct telephony writes.

## Required behavior

After each completed call:

- the middleware invokes `codestra.crm.call.followup.register_completed_call(payload)` through authenticated Odoo RPC;
- one pending record is created for the assigned agent;
- duplicate deliveries return the first record and do not create a second popup;
- the Odoo bus opens the agent's post-call modal;
- a browser reconnect reloads unfinished actions;
- the modal collects a structured outcome and notes;
- the agent can schedule a callback or appointment with date, time, and duration;
- the calendar event includes the linked client and assigned agent as attendees;
- Odoo shows the assigned agent a native in-app calendar popup 30 minutes before the event;
- Odoo queues the 15-minute reminder email separately for each attendee, therefore reaching both client and agent;
- the agent can review and edit the immediate post-call email before it is queued;
- calendar reschedules and cancellations synchronize back to the follow-up record;
- the CRM lead exposes the call history and next callback.

## Review first; do not deploy first

From a clean worktree:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
python scripts/validate_odoo_crm_call_followup.py
python -m compileall -q \
  odoo_addons/codestra_crm_call_followup \
  scripts/validate_odoo_crm_call_followup.py
```

Review every Python, XML, JavaScript, SCSS, security, and test file. Fix any defect on the feature branch with focused commits. Do not weaken a security rule merely to make a test pass.

## Mandatory staging sequence

Use a disposable test database first, then a sanitized staging copy. Substitute actual local paths and database names; do not paste secrets into the shell history.

### 1. Capture the starting state

```bash
git rev-parse HEAD
odoo-bin --version
psql -Atqc "select version();" <staging_database>
```

Record:

- feature SHA;
- Odoo build/version;
- PostgreSQL version;
- current addon path;
- active Odoo worker and bus topology;
- outgoing mail server identity;
- staging database backup and filestore backup locations.

### 2. Clean install test

```bash
createdb <disposable_test_database>
./odoo-bin \
  -d <disposable_test_database> \
  --addons-path=<repository>/odoo_addons,<odoo_core>/addons \
  -i codestra_crm_call_followup \
  --test-enable \
  --test-tags /codestra_crm_call_followup \
  --stop-after-init \
  --log-level=test
```

The command must exit zero. Save the complete log as PR evidence.

### 3. Upgrade test on staging copy

Back up PostgreSQL and the Odoo filestore before the upgrade.

```bash
./odoo-bin \
  -d <staging_database> \
  --addons-path=<repository>/odoo_addons,<odoo_core>/addons \
  -u codestra_crm_call_followup \
  --stop-after-init
```

Restart only the staging Odoo services and verify `/web`, websocket/long-polling bus traffic, the CRM application, Calendar, and the mail queue.

### 4. Create staging identities

- Create a non-human integration user.
- Assign only the required company access and `Call Follow-up / Integration Service`.
- Generate its API key through Odoo.
- Store the key in the middleware secret store.
- Create or select one test agent assigned to `Call Follow-up / Agent` with a valid email and time zone.
- Use a synthetic CRM customer and synthetic email address only.

### 5. Middleware adapter

Implement the adapter in the middleware repository/service, not in Odoo telephony code. Use authenticated Odoo RPC and the documented payload. Required middleware controls:

- deterministic `event_id` derived from the authoritative completed-call event;
- correlation ID propagation;
- bounded timeout;
- retry with exponential backoff and jitter;
- idempotent replay using the same `event_id`;
- dead-letter or operational exception after the retry budget;
- no logging of API keys, email bodies, or unrestricted customer data;
- response validation requiring `followup_id`, `event_id`, `state`, and `replayed`;
- metric counters for success, replay, validation failure, authorization failure, timeout, and dead-letter.

Do not acknowledge the middleware event as complete until Odoo returns a valid registration response or the event is durably retained for retry.

## Mandatory acceptance tests

### Authorization and isolation

- A normal agent cannot invoke `register_completed_call`.
- The integration user cannot register an event for a company outside its allowed companies.
- An agent cannot read another agent's follow-up.
- A manager can review company-scoped records.
- Human users cannot create or delete immutable call records from UI, import, or RPC.

### Idempotency and race safety

- Deliver the same event twice sequentially: one record, one popup request, second response `replayed=true`.
- Deliver the same event concurrently from at least two workers: one database row, no uncaught 500, one effective popup.
- Retry after a simulated network timeout with the same event ID.

### User experience

- A completed-call event opens the modal only for the assigned logged-in agent.
- Multiple completed calls queue and open one modal at a time.
- Closing a modal without completing it leaves the action pending and it reappears after browser reload.
- Outcome and notes save correctly and appear in the CRM lead history.
- Do-not-call and wrong-number outcomes cannot be paired with a new appointment.
- The layout is usable at desktop and narrow browser widths.

### Calendar and reminders

- Callback and appointment both create calendar events.
- Client and agent are attendees.
- Agent sees the Odoo native notification 30 minutes before the event.
- Mail-capture proves one 15-minute reminder reaches the client and one reaches the agent.
- Rescheduling the calendar event updates the follow-up timestamp and duration.
- Cancelling/removing the event clears the scheduled next step without deleting the completed-call audit record.
- Time zones and daylight-saving boundaries render correctly for the agent and client.

### Email

- Immediate email is editable in the modal.
- Save queues the message; it does not force synchronous SMTP delivery.
- Sender, recipient, CC, reply path, subject, and rendered HTML are correct.
- Missing or invalid recipient addresses fail with a clear validation message.
- SMTP failure leaves the message visible in Odoo's mail queue for normal retry/operations.

## Production gate

Production is `NO_GO` unless all of these are true:

```text
DRAFT_PR=CONVERTED_TO_READY
REQUIRED_CHECKS=PASS
INDEPENDENT_REVIEW=APPROVED
EXACT_HEAD_SHA_RECORDED
STAGING_CLEAN_INSTALL=PASS
STAGING_UPGRADE=PASS
ODOO_TESTS=PASS
DUPLICATE_RACE_TEST=PASS
BUS_POPUP_TEST=PASS
CALENDAR_30_MIN_POPUP=PASS
CLIENT_15_MIN_EMAIL=PASS
AGENT_15_MIN_EMAIL=PASS
MULTI_COMPANY_ISOLATION=PASS
DATABASE_BACKUP=VERIFIED
FILESTORE_BACKUP=VERIFIED
ROLLBACK_REHEARSAL=PASS
CHANGE_WINDOW=APPROVED
```

Do not merge or deploy while any value is missing or failed.

## Production release procedure

After approval, merge the exact reviewed head. Deploy by immutable merged SHA, not by a moving branch name.

1. Record current production application SHA and Odoo module state.
2. Back up PostgreSQL and the matching filestore; verify both artifacts are readable.
3. Put the exact merged repository SHA on the Odoo host.
4. Confirm the addon path is present without changing unrelated addons.
5. Run the module upgrade with `--stop-after-init` against production.
6. Restart Odoo workers using the existing service manager.
7. Verify web, workers, cron, bus/websocket, database, and mail queue health.
8. Enable the feature only for a small canary agent group.
9. Send synthetic completed-call events; do not place a live call solely for deployment testing.
10. Observe application logs, Odoo mail queue, bus delivery, error rate, duplicate count, and database health.
11. Expand agent assignment only after canary acceptance.

## Rollback

Never attempt an in-place schema downgrade.

If the production upgrade or canary fails:

1. stop further completed-call delivery to the Odoo adapter while retaining events durably in middleware;
2. remove agent access to the feature group;
3. stop Odoo workers;
4. restore the pre-change PostgreSQL backup and matching filestore when the module changed schema or data;
5. restore the previously recorded application SHA;
6. start Odoo and verify the pre-change health checks;
7. keep retained middleware events blocked until the incident owner decides whether to replay or discard synthetic events;
8. attach timestamps, logs, rollback evidence, and impact to the change record.

Do not uninstall the module as a production rollback strategy because uninstalling can delete module-owned records.

## Required Codex completion report

Codex must finish with one exact report containing:

```text
CURRENT_DIRECTORY=
BRANCH=
STARTING_SHA=
FINAL_SHA=
COMMITS_CREATED=
STATIC_GATE=
CLEAN_INSTALL_TEST=
ODOO_MODULE_TESTS=
STAGING_UPGRADE_TEST=
BUS_POPUP_TEST=
IDEMPOTENCY_TEST=
CONCURRENT_DUPLICATE_TEST=
CALENDAR_30_MIN_POPUP_TEST=
CLIENT_15_MIN_EMAIL_TEST=
AGENT_15_MIN_EMAIL_TEST=
MULTI_COMPANY_TEST=
SMTP_QUEUE_TEST=
DATABASE_BACKUP=
FILESTORE_BACKUP=
ROLLBACK_REHEARSAL=
PR_NUMBER=
PR_HEAD_SHA=
MERGED=YES|NO
PRODUCTION_DEPLOYED=YES|NO
PRODUCTION_SHA=
GO_NO_GO=
BLOCKERS=
```

A partial or verbal-only report is not production evidence.
