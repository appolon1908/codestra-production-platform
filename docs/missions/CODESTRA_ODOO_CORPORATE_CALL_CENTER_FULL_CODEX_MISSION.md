# Codestra Odoo 19 Corporate Call Center

## Full Codex Engineering, API, Database, Design and Production Mission

**Mission owner:** Codestra  
**Primary platform:** Odoo 19 + Codestra middleware + VICIdial + n8n  
**Primary execution host:** Server A — `65.109.65.169` / `10.40.0.1`  
**VICIdial host:** `65.21.67.207` — preserve this server and discover its current private address  
**Provider host:** `37.27.128.39` / `10.40.0.4`  
**Canonical API:** `https://api.codestra.co`  
**Canonical identity issuer:** `https://auth.codestra.co/realms/codestra`  
**Primary platform repository:** `appolon1908-hue/codestra-production-platform`  
**Existing Odoo module:** `codestra_vicidial_crm`

---

## 1. Mission objective

Audit the existing Odoo 19 implementation and its `codestra_vicidial_crm` module; preserve all working functionality and existing records; repair defects; implement all missing corporate call-center, client-operations, agent-management, QA, compliance, billing, reporting and integration functionality; improve the agent and supervisor user experience; construct a versioned and secured API; certify the Odoo/VICIdial browser screen-pop; publish a reviewed immutable release; deploy it through isolated staging; and promote it safely to production.

This is an implementation mission, not a documentation-only audit. Codex must inspect, design, code, migrate, test, document, open protected pull requests, build immutable releases, stage, certify and deploy all functionality that passes its production gates.

Codex must never force a failed gate to `PASS` or bypass GitHub review, environment approval, credentials, consent, provider authorization, backup, restore, canary or maintenance-window controls.

---

## 2. Authoritative system responsibilities

| System | Responsibility |
|---|---|
| Odoo 19 | Corporate CRM, customer 360, agent desktop, tickets, campaigns, QA, client operations, reporting and business records |
| VICIdial | PBX, predictive dialing, inbound queues, live call state, agent telephony state and recordings |
| Codestra middleware | Authorization, event validation, idempotency, outbox delivery, reconciliation and controlled downstream writes |
| Kong | Canonical API ingress, authentication enforcement, route policy, rate limits and request correlation |
| Keycloak | Human OIDC and machine client-credential identities; canonical issuer is `auth.codestra.co` only |
| n8n | Explicitly allowlisted business automations; never the system of record |
| Klyrow/Postal | Email sending, receiving, mailbox and domain operations through the provider gate |
| Telnexa/Jasmin | SMS sending, receiving, compliance and provider operations through the provider gate |
| Caddy | Public and private TLS termination according to the active host-Caddy architecture |
| PostgreSQL | Odoo and integration data with least-privilege roles |
| Redis | Queues, leases and temporary coordination; never authoritative customer storage |

Do not make Odoo a second dialer. Do not move or redesign the VICIdial server. Do not let n8n become the authoritative database. Do not allow Odoo to directly write VICIdial tables or provider databases.

---

## 3. Safety and engineering rules

1. Never reveal, print, log, paste or commit passwords, tokens, private keys, SMTP credentials, client secrets, session cookies or secret-file contents.
2. Develop in an isolated Git working directory. Never develop inside the live Odoo add-ons directory.
3. Preserve existing Odoo external IDs, records, audit history and stable API contracts.
4. Do not perform a big-bang rewrite of `codestra_vicidial_crm`. Repair it and extract capabilities progressively.
5. Extend Odoo using installable custom add-ons. Do not modify Odoo core source.
6. Use Odoo ORM and service APIs. External systems must not write directly to Odoo PostgreSQL.
7. Use migrations for every schema or data change. Migrations must be restartable and idempotent.
8. Use multi-company, tenant and campaign record rules for every business object.
9. Avoid unrestricted `sudo()` in Odoo code. Every necessary elevated operation must be narrow, justified, tested and audited.
10. Keep recordings in protected external storage. Odoo stores only controlled references, metadata and access logs.
11. All side effects use a transactional outbox and idempotency key.
12. All privileged supervisor controls require a dedicated permission and immutable audit entry.
13. Customer communications require the correct campaign, consent, sender, recipient, template, geographic policy and provider gate.
14. Keep unrelated production flags false while certifying one channel.
15. Never enable email, SMS, callbacks, VICIdial controls or PSTN dialing simultaneously.

---

## 4. Required repository construction

Use this logical repository layout unless the audited repository already provides an equivalent reviewed structure:

```text
odoo-addons/
  codestra_cc_core/
  codestra_cc_vicidial/
  codestra_cc_agent_desktop/
  codestra_cc_campaign/
  codestra_cc_disposition/
  codestra_cc_customer_360/
  codestra_cc_supervisor/
  codestra_cc_quality/
  codestra_cc_compliance/
  codestra_cc_omnichannel/
  codestra_cc_workforce/
  codestra_cc_identity/
  codestra_cc_mailbox/
  codestra_cc_automation/
  codestra_cc_reliability/
  codestra_cc_analytics/
  codestra_cc_audit/
  codestra_client_operations/
  codestra_revenue_assurance/
  codestra_data_quality/
  codestra_case_management/
  codestra_agent_onboarding/
  codestra_training_academy/
  codestra_client_portal/
  codestra_campaign_publishing/
  codestra_ai_agent_assistant/
api/
  contracts/
  schemas/
  examples/
  openapi/
deploy/
  compose/
  environments/
  migrations/
  rollback/
docs/
  architecture/
  agents/
  supervisors/
  administrators/
  compliance/
tests/
  contracts/
  browser/
  load/
  security/
  migration/
```

Each Odoo module must contain a valid manifest, explicit dependencies, access control, record rules, models, views, tests, migrations and documentation. Avoid circular module dependencies.

---

## 5. Module and feature requirements

### 5.1 `codestra_cc_core`

Provide the canonical interaction, call-leg, agent-state, campaign link and customer-link models. Every interaction must have one globally unique UUID and may contain multiple call legs, transfers, messages and business outcomes.

### 5.2 `codestra_cc_vicidial`

Provide idempotent VICIdial event ingestion, normalized phone lookup, browser screen-pop, click-to-call requests, agent state synchronization, transfers, recording references and final call reconciliation. Use reviewed APIs or middleware events—not direct database writes.

### 5.3 `codestra_cc_agent_desktop`

Create one responsive agent workspace containing customer profile, campaign, script, consent warnings, active call state, prior interactions, notes, Helpdesk/CRM context, knowledge, callback tools and mandatory wrap-up.

### 5.4 `codestra_cc_campaign`

Manage client, company, Odoo team, VICIdial campaign/list, queue, DID, caller ID, hours, timezone, language, skills, script, forms, dispositions, SLAs, email domain, SMS sender, recording, retention, compliance and automation allowlists.

### 5.5 `codestra_cc_disposition`

Provide campaign-specific dispositions and sub-dispositions with conditional required fields, wrap-up timing, next actions and deterministic automation mappings.

### 5.6 `codestra_cc_customer_360`

Build a single chronological timeline for calls, tickets, CRM activities, email, SMS, appointments, quotations, orders, consent, complaints and controlled recording references.

### 5.7 `codestra_cc_supervisor`

Provide live agent and queue dashboards, SLA alerts, escalations and explicitly authorized VICIdial listen/whisper/barge/pause/force-logout requests. Audit every action.

### 5.8 `codestra_cc_quality`

Provide QA scorecards, recording review, weighted questions, critical failures, agent acknowledgment, disputes, calibration, coaching, re-evaluation and QA trends.

### 5.9 `codestra_cc_compliance`

Manage consent source/version/time, DNC, email/SMS opt-outs, calling windows, destination timezone, recording disclosures, approved caller IDs, jurisdiction policies, retention, complaints and suppression lists.

### 5.10 `codestra_cc_omnichannel`

Thread email, SMS and later approved chat conversations into the same interaction record. All external delivery must pass through middleware and the provider-specific production gate.

### 5.11 `codestra_cc_workforce`

Integrate Odoo Employees, Planning and Attendances for schedules, breaks, availability, adherence, occupancy and staffing. Do not derive payroll from unverified telephony events.

### 5.12 `codestra_cc_identity`

Provision and deactivate Keycloak, Odoo and VICIdial identities, extensions, campaign memberships, skills and supervisor assignments. Use `auth.codestra.co` only.

### 5.13 `codestra_cc_mailbox`

Assign a verified campaign domain and provision `firstname@campaign-domain`. Normalize names, verify sending/receiving, and fail closed on duplicates. A manager must resolve duplicate first names—never silently replace an existing mailbox.

### 5.14 `codestra_cc_automation`

Map approved dispositions and business events to allowlisted n8n workflows. The browser must never supply an arbitrary executable workflow ID.

### 5.15 `codestra_cc_reliability`

Implement outbox, inbox, idempotency, retry, lease recovery, dead-letter handling, replay authorization, schema versions, correlation and reconciliation.

### 5.16 `codestra_cc_analytics`

Report ASA, abandonment, AHT, talk/hold/wrap time, FCR, transfers, callback SLA, contact/conversion, occupancy, adherence, QA, complaints, opt-outs, delivery, revenue and margin.

### 5.17 `codestra_cc_audit`

Provide append-only audit records for record access, exports, role changes, provider actions, supervisor controls, campaign publishing and configuration changes.

### 5.18 Corporate operations extensions

Implement:

- `codestra_client_operations`: clients, contracts, campaign onboarding, SLAs and authorized contacts.
- `codestra_revenue_assurance`: rate plans, billable usage, provider costs, invoices and margin.
- `codestra_data_quality`: phone/email normalization, duplicate detection, merge review and incomplete-data queues.
- `codestra_case_management`: complaints, disputes, refunds, incidents and executive escalation.
- `codestra_agent_onboarding`: hiring, documents, checks, equipment, access and offboarding.
- `codestra_training_academy`: courses, scripts, quizzes, certifications and retraining.
- `codestra_client_portal`: client KPIs, tickets, invoices, leads, approved recordings and evidence.
- `codestra_campaign_publishing`: draft/review/approve/publish/version/rollback campaign configurations.
- `codestra_ai_agent_assistant`: reviewed summaries, knowledge suggestions and draft responses. AI must never independently set consent, DNC, refunds or send customer messages.

---

## 6. Canonical Odoo data model

Use the following as the minimum schema. Codex may extend it after auditing existing fields, but must preserve compatibility and avoid duplicate concepts.

| Odoo model | PostgreSQL table | Important fields | Required constraints/indexes |
|---|---|---|---|
| `codestra.cc.interaction` | `codestra_cc_interaction` | `uuid`, `company_id`, `campaign_id`, `partner_id`, `lead_id`, `ticket_id`, `channel`, `direction`, `state`, `started_at`, `ended_at` | Unique `uuid`; indexes on company/campaign/partner/state/date |
| `codestra.cc.call.leg` | `codestra_cc_call_leg` | `interaction_id`, `external_call_id`, `parent_leg_id`, `agent_id`, `extension`, `queue`, ring/answer/hold/end timestamps, hangup cause | Unique `(source_system, external_call_id)`; indexes on interaction/agent/date |
| `codestra.cc.event` | `codestra_cc_event` | `event_id`, `schema_version`, `event_type`, `source`, `occurred_at`, `received_at`, `correlation_id`, `payload_hash`, `status` | Unique `(source,event_id)`; indexes on type/status/received_at |
| `codestra.cc.campaign` | `codestra_cc_campaign` | company/client, VICIdial mapping, teams, DIDs, hours, timezone, language, script, policy and provider configuration | Unique active external campaign mapping per company |
| `codestra.cc.queue` | `codestra_cc_queue` | campaign, external queue ID, direction, language, SLA, priority | Unique `(campaign_id,external_queue_id)` |
| `codestra.cc.disposition` | `codestra_cc_disposition` | campaign, code, label, category, required fields, follow-up mapping, active/version | Unique `(campaign_id,code,version)` |
| `codestra.cc.wrapup` | `codestra_cc_wrapup` | interaction, agent, disposition, notes, started/completed timestamps, next action | One completed wrap-up per agent call leg unless reviewed reopen |
| `codestra.cc.callback` | `codestra_cc_callback` | interaction, contact, scheduled time, timezone, owner, state, consent snapshot | Index on owner/state/scheduled time; idempotent creation key |
| `codestra.cc.consent` | `codestra_cc_consent` | partner, channel, purpose, state, source, version, timestamp, expiry, evidence reference | Unique active consent per partner/channel/purpose/version policy |
| `codestra.cc.suppression` | `codestra_cc_suppression` | normalized destination, channel, reason, source, effective/expiry time | Index destination/channel; block checked before side effect |
| `codestra.cc.recording` | `codestra_cc_recording` | interaction/call leg, protected storage reference, duration, checksum, access classification, retention date | Never store raw secret URL; indexes on call and retention date |
| `codestra.cc.qa.review` | `codestra_cc_qa_review` | recording, scorecard/version, evaluator, agent, result, critical failure, dispute state | Unique active final review per recording/scorecard version |
| `codestra.cc.agent.profile` | `codestra_cc_agent_profile` | user, employee, Keycloak subject, VICIdial user, extension, skills, campaign assignments | Unique active identity mappings and extension |
| `codestra.cc.agent.state` | `codestra_cc_agent_state` | agent, state, reason, source, effective time, interaction | Index agent/time; current-state uniqueness |
| `codestra.cc.mailbox` | `codestra_cc_mailbox` | agent, campaign, domain, local part, address, provider ID, inbound/outbound status | Case-insensitive unique address |
| `codestra.cc.outbox` | `codestra_cc_outbox` | event UUID, aggregate, action, destination, payload version, state, attempts, lease, next attempt | Unique idempotency key; indexes state/next attempt/lease |
| `codestra.cc.reconciliation` | `codestra_cc_reconciliation` | system, range, expected/observed counts, mismatches, evidence, state | Unique run UUID; indexes system/state/date |
| `codestra.cc.audit.event` | `codestra_cc_audit_event` | actor, subject, action, object, before/after hashes, request ID, IP, timestamp | Append-only; indexes actor/object/action/time |
| `codestra.client.contract` | `codestra_client_contract` | client, services, pricing, SLA, start/end, approval state | Versioned active-contract rules |
| `codestra.rate.plan` | `codestra_rate_plan` | client/campaign, billable unit, rate, currency, effective dates | No overlapping effective ranges for same scope |
| `codestra.billing.usage` | `codestra_billing_usage` | source interaction/event, units, cost, revenue, state, invoice link | Unique source usage key |
| `codestra.provisioning.job` | `codestra_provisioning_job` | requested identity/resources, approvals, per-system state, rollback state | Idempotency key and state-transition validation |

Store core searchable fields in typed columns. JSON may retain a sanitized, versioned raw-event body, but must not replace indexed business fields. Partition or archive high-volume event and audit tables if evidence proves it necessary.

---

## 7. Database construction and migrations

1. Inspect existing models and map every old field to the target model before writing migrations.
2. Preserve `codestra_vicidial_crm` external IDs and existing call/lead/ticket links.
3. Add missing normalized phone fields to contacts/leads with indexed, deterministic normalization.
4. Backfill new UUIDs and source identifiers without rewriting historical business meaning.
5. Detect duplicates before enabling unique constraints; create a manager review queue for ambiguous records.
6. Add foreign keys, check constraints and indexes through reviewed migrations.
7. Never delete records to make a migration pass.
8. Test fresh installation, upgrade from the deployed version, interrupted migration restart and restoration of the pre-upgrade backup.
9. Include migration checksums and before/after record counts.
10. Run `ANALYZE` on materially changed tables and record query plans for screen-pop lookup.

Database acceptance:

```text
MIGRATION_RESTARTABLE=PASS
HISTORICAL_RECORD_COUNTS_MATCH=PASS
ORPHAN_RELATIONSHIPS=0
DUPLICATE_EXTERNAL_EVENT_IDS=0
PHONE_LOOKUP_INDEX=PASS
SCREEN_POP_QUERY_P95_MS<=250
ROLLBACK_RESTORE=PASS
```

---

## 8. Canonical API construction

### 8.1 API boundary

Expose approved routes through Kong at:

```text
https://api.codestra.co/v1/contact-center/
```

Odoo browser sessions may use Odoo JSON-RPC internally for standard UI operations, but cross-system integrations must use the versioned API and middleware contracts below.

### 8.2 Authentication

- Human users: Keycloak Authorization Code + PKCE using `auth.codestra.co`.
- Machine clients: Keycloak Client Credentials with short-lived tokens.
- Private provider/VICIdial hops: existing mTLS service identity plus token/authorization policy.
- Every request includes correlation and request IDs.
- Never use long-lived username/password authentication between services.

### 8.3 Standard headers

```text
Authorization: Bearer <short-lived-token>
Content-Type: application/json
X-Request-ID: <uuid>
X-Correlation-ID: <uuid>
Idempotency-Key: <uuid-or-deterministic-key>   # required for POST side effects
X-Event-Schema-Version: 1                     # event endpoints
```

### 8.4 Required endpoints

| Method | Endpoint | Purpose | Permission |
|---|---|---|---|
| `GET` | `/v1/contact-center/healthz` | Process health only | Private monitor |
| `GET` | `/v1/contact-center/readyz` | DB, queue and dependency readiness | Private monitor |
| `POST` | `/v1/contact-center/events/vicidial` | Receive versioned call/agent events | VICIdial service |
| `POST` | `/v1/contact-center/events/provider` | Receive normalized email/SMS results | Provider service |
| `POST` | `/v1/contact-center/screen-pop/resolve` | Resolve an authorized customer context | Agent service/browser |
| `GET` | `/v1/contact-center/interactions/{uuid}` | Read an authorized interaction | Agent/supervisor |
| `POST` | `/v1/contact-center/interactions/{uuid}/disposition` | Submit mandatory wrap-up | Assigned agent |
| `POST` | `/v1/contact-center/interactions/{uuid}/callback` | Schedule authorized callback | Agent/supervisor |
| `POST` | `/v1/contact-center/interactions/{uuid}/transfer` | Request controlled transfer | Agent |
| `GET` | `/v1/contact-center/agents/me/state` | Current agent state | Agent |
| `POST` | `/v1/contact-center/agents/me/state` | Request permitted state change | Agent |
| `GET` | `/v1/contact-center/supervisor/queues` | Queue/agent operational view | Supervisor |
| `POST` | `/v1/contact-center/supervisor/actions` | Restricted live control request | Authorized supervisor |
| `GET` | `/v1/contact-center/campaigns/{id}/configuration` | Effective published configuration | Assigned roles |
| `POST` | `/v1/contact-center/campaigns/{id}/publish` | Publish approved version | Campaign approver |
| `POST` | `/v1/contact-center/provisioning/agents` | Start idempotent agent provisioning | Authorized manager |
| `GET` | `/v1/contact-center/provisioning/jobs/{uuid}` | Provisioning status | Authorized manager |
| `POST` | `/v1/contact-center/reconciliation/runs` | Start bounded reconciliation | Integration operator |
| `GET` | `/v1/contact-center/reconciliation/runs/{uuid}` | Reconciliation result | Operator/auditor |
| `GET` | `/v1/contact-center/reports/operations` | Authorized KPI aggregation | Reporting roles |
| `GET` | `/v1/contact-center/audit/events` | Restricted audit search | Auditor/admin |

No administrative endpoint may expose secret values. Metrics must remain private and authenticated.

### 8.5 Event envelope

Use one versioned envelope for all machine events:

```json
{
  "event_id": "evt_018f...",
  "event_type": "call.ended",
  "schema_version": 1,
  "occurred_at": "2026-08-23T12:00:00Z",
  "source": "vicidial",
  "tenant_id": "company-uuid",
  "campaign_id": "campaign-uuid",
  "correlation_id": "interaction-uuid",
  "subject": {
    "type": "call_leg",
    "id": "vicidial-call-id"
  },
  "data": {}
}
```

Event types must include:

```text
call.created
call.ringing
call.answered
call.held
call.resumed
call.transferred
call.ended
call.disposition_submitted
agent.login
agent.ready
agent.paused
agent.wrapup
agent.logout
callback.created
callback.completed
email.accepted
email.delivered
email.bounced
email.received
sms.accepted
sms.delivered
sms.failed
sms.received
provisioning.completed
provisioning.failed
```

Reject unknown schema versions fail-closed. Store the event once, return the prior result for an exact replay, and reject an event ID reused with a different body hash.

### 8.6 Screen-pop request and response

Request:

```json
{
  "call_id": "external-call-id",
  "campaign_external_id": "MONEYBEE",
  "direction": "inbound",
  "telephone": "+12125550100",
  "agent_external_id": "6101"
}
```

Response:

```json
{
  "interaction_uuid": "uuid",
  "match_state": "single_match",
  "partner_id": 123,
  "lead_id": null,
  "ticket_id": 456,
  "authorized_view": "/web#id=123&model=res.partner&view_type=form",
  "consent_warnings": [],
  "campaign_script_version": "7",
  "required_actions": []
}
```

Never accept a browser-supplied Odoo record ID as proof of authorization. Resolve identity, campaign and record access server-side.

### 8.7 Error contract

```json
{
  "error": {
    "code": "CONSENT_REQUIRED",
    "message": "The requested channel is not authorized.",
    "request_id": "uuid",
    "retryable": false
  }
}
```

Use stable machine codes, safe human messages and appropriate HTTP status codes. Never expose tracebacks or database details publicly.

---

## 9. Agent desktop design

Build for 1366×768, 1440×900 and larger displays.

### Header

- Customer name and verification status
- Campaign, queue and language
- Inbound/outbound indicator
- Live timer and current call state
- Consent/DNC/recording warning
- VIP, complaint or account-risk indicator

### Left column

- Customer profile
- Normalized phones and emails
- Account/company information
- Products/services
- Open opportunities, tickets and callbacks
- Compact prior-interaction timeline

### Center column

- Versioned campaign script
- Dynamic campaign form
- Required compliance statement
- Notes
- Qualification, sale or support workflow
- Contextual Knowledge suggestions

### Right column

- Approved live call controls
- Transfer/conference/hold controls
- Callback scheduling
- Supervisor assistance
- Email/SMS controls shown only when the channel is authorized

### Sticky wrap-up area

- Disposition/sub-disposition
- Conditional required fields
- Outcome notes
- Follow-up and callback owner
- Wrap-up countdown
- Save and return-to-ready action

An agent may not return to `Ready` until required wrap-up fields pass validation. Browser refresh must restore active interaction context.

---

## 10. Client and campaign construction

Provide a guided, versioned onboarding wizard:

1. Client company and authorized contacts
2. Contract, currency and billing model
3. Campaign purpose and direction
4. Operating hours, timezone and holidays
5. Odoo CRM/Helpdesk teams
6. VICIdial campaign, lists, queue and DID
7. Approved caller IDs
8. Languages and agent skills
9. Scripts and dynamic forms
10. Dispositions and next actions
11. Callback and escalation rules
12. SLA targets
13. Consent and jurisdiction policies
14. Recording and retention policies
15. Email domain and mailbox policy
16. SMS sender and templates
17. n8n workflow allowlist
18. Reporting and portal access
19. Pricing, provider cost and margin rules
20. Independent review and publish

Nothing becomes effective until an approved configuration version is published. Retain prior versions for rollback.

Create initial templates for Transportation/Logistics, MoneyBee Loans, Codestra Web and AI, Support, Billing and Student Repayment without activating real traffic.

---

## 11. Identity, mailbox and agent lifecycle

One approved provisioning job must coordinate:

- Keycloak user and roles
- Odoo user and employee
- VICIdial identity and extension
- Campaign and skill assignments
- Supervisor relationship
- Verified campaign-domain mailbox
- Email and SMS sender permissions
- Training/certification requirements

Provisioning must be transactional at the workflow level: record every per-system result, compensate completed steps when a later required step fails, and never leave unexplained partial access.

Offboarding must disable interactive access and sending/control authority immediately while preserving legally required historical records.

---

## 12. Roles and authorization

Implement and test:

- Agent
- Senior Agent
- Closer
- QA Analyst
- Supervisor
- Campaign Manager
- Client Operations Manager
- Workforce Manager
- Compliance Officer
- Billing Manager
- Reporting Viewer
- Integration Operator
- Service Account
- Platform Administrator

Required negative tests:

- Agent cannot read another campaign.
- Agent cannot access restricted recordings.
- Agent cannot change consent evidence.
- QA cannot alter original call events.
- Supervisor cannot control an unrelated company or campaign.
- Reporting users cannot change records.
- Billing users cannot operate live calls.
- Browser users cannot invoke raw service endpoints.
- Service accounts cannot use interactive login.
- No user can choose an arbitrary n8n workflow or provider sender.

---

## 13. Reliability and reconciliation

All side effects must follow:

```text
Odoo transaction
  -> transactional outbox
  -> middleware validation
  -> authorized downstream provider
  -> delivery/result event
  -> inbox deduplication
  -> Odoo reconciliation
```

Implement bounded exponential backoff, attempt limits, lease expiry, stale-job recovery, dead-letter review, authorized manual replay and end-to-end correlation IDs.

Reconciliation must compare at least:

- VICIdial calls vs middleware events vs Odoo interactions
- Dispositions vs Odoo wrap-ups and next actions
- Klyrow accepted/delivered/bounced/received vs Odoo timeline
- Telnexa accepted/delivered/failed/received vs Odoo timeline
- Provisioned identities across Keycloak/Odoo/VICIdial/provider
- Billable usage vs source interactions

Never hide or automatically discard a mismatch.

---

## 14. Reporting and profitability

Implement definitions and tested calculations for:

- ASA
- Abandonment rate
- AHT
- Talk, hold and after-call-work time
- First-call resolution
- Transfer success
- Callback SLA
- Contact and conversion rates
- Sales/revenue per agent hour
- Occupancy and adherence
- QA score and critical failures
- Complaint and opt-out rates
- Email/SMS delivery and response
- Provider cost
- Cost per call/lead/appointment/sale
- Revenue and gross margin by client/campaign/agent/team

Every dashboard must support date, company, client, campaign, queue, team, agent, language and disposition filters subject to record rules.

---

## 15. Implementation phases

### Phase 0 — Baseline

Inventory source, runtime, modules, schema, integrations, flags, tests and evidence. Complete encrypted backup and isolated restore.

### Phase 1 — Repair and compatibility

Fix existing defects, deprecated Odoo 18 patterns, identity issuer drift, broken access rules, inefficient lookup and unreliable VICIdial/event behavior. Add regression tests before changing behavior.

### Phase 2 — Core schema and API

Implement core models, migrations, event inbox/outbox, authorization, API contracts, OpenAPI specification and contract tests.

### Phase 3 — Agent, campaign and customer UX

Implement the agent desktop, campaign publishing, dispositions, customer 360 and browser screen-pop.

### Phase 4 — Corporate operations

Implement QA, supervisors, compliance, workforce, onboarding, training, client portal, case management, revenue assurance and data quality.

### Phase 5 — Integrations

Certify Keycloak, Kong, middleware, VICIdial, n8n, Klyrow and Telnexa contracts with synthetic data and fail-closed provider gates.

### Phase 6 — Security and performance

Complete negative authorization, dependency, secret, image, accessibility, load and recovery testing.

### Phase 7 — Protected release

Open PRs, resolve findings, obtain exact-head independent approval, merge normally, produce signed immutable artifacts, SBOM, provenance and checksums.

### Phase 8 — Isolated staging

Install the exact artifact, migrate a sanitized database, run browser and contract certification, verify backup/restore and complete the required soak.

### Phase 9 — Production promotion

Use an approved maintenance tuple, zero-active-call or reviewed drain procedure, verified rollback and bounded canary. Activate channels independently and reconcile after every expansion.

---

## 16. Required testing

Run and retain evidence for:

- Python/Odoo unit tests
- ORM constraints and computed-field tests
- ACL and record-rule tests
- API/controller and OpenAPI contract tests
- JavaScript component tests
- Browser screen-pop tests
- VICIdial event replay and ordering tests
- Middleware integration tests
- n8n allowlist tests
- Outbox/inbox/idempotency tests
- Migration and interrupted-migration tests
- Backup and isolated restore
- Accessibility and keyboard operation
- Static analysis and formatting
- Dependency and container vulnerability audits
- Secret scanning
- 150 concurrent agent sessions
- 50 call events/second for five minutes
- Worker restart during processing
- Provider/middleware unavailability and recovery

Performance targets:

```text
SCREEN_POP_MATCH_ACCURACY=100_PERCENT_IN_CERTIFICATION_FIXTURES
SCREEN_POP_P95_SECONDS<2
DISPOSITION_SAVE_P95_SECONDS<1.5
SCREEN_POP_DATABASE_QUERY_P95_MS<250
DUPLICATE_EVENT_SIDE_EFFECTS=0
LOST_FINAL_INTERACTIONS=0
CROSS_TENANT_EXPOSURES=0
UNEXPECTED_CUSTOMER_MESSAGES=0
```

---

## 17. GitHub and immutable release

1. Create dedicated branches from the protected baseline.
2. Make small, signed commits.
3. Run all CI, migration, security and contract tests.
4. Open PRs with architecture, migration, risk and rollback information.
5. Resolve every review finding.
6. Obtain fresh independent approval against the exact final head.
7. Merge normally without administrator bypass.
8. Build one immutable version with digest.
9. Generate SBOM, vulnerability report, provenance, release notes and checksums.
10. Verify the published artifact before staging or production.

Never deploy an uncommitted tree, mutable tag, locally modified production directory or candidate whose source does not match its release evidence.

---

## 18. Production rollout

Before production:

```text
BACKUP_STATUS=PASS
RESTORE_REHEARSAL_GATE=PASS
SIGNED_IMMUTABLE_RELEASE=PASS
SBOM_STATUS=PASS
PROVENANCE_STATUS=PASS
INDEPENDENT_APPROVAL=PASS
STAGING_CERTIFICATION=PASS
ROLLBACK_REHEARSAL=PASS
PENDING_UNAPPROVED_OUTBOX=0
```

Activation order:

1. Deploy database-compatible add-ons.
2. Run reviewed Odoo module upgrades.
3. Restart only required Odoo services/workers.
4. Verify Odoo, database and queue health.
5. Enable VICIdial read/screen-pop only.
6. Run one synthetic inbound screen-pop.
7. Run one authorized internal agent workflow.
8. Enable Odoo writes and final-call reconciliation through a bounded canary.
9. Process 5–10 naturally finalized approved calls.
10. Complete one-hour monitoring and reconciliation.
11. Complete one-business-day monitoring and reconciliation.
12. Expand campaign by campaign.
13. Activate callbacks, n8n, email, SMS and dialing independently only after each provider and compliance gate passes.

Email remains closed until Klyrow reports its production gate open and a bounded canary is confirmed. SMS remains closed until Telnexa is certified. PSTN dialing remains closed until DIDWW/provider, caller-ID, consent, geographic policy and maintenance-window approvals pass.

---

## 19. Automatic rollback conditions

Close the affected channel and execute the reviewed rollback if any of these occur:

- Health or migration failure
- Authentication or authorization regression
- Screen-pop mismatch
- Lost or duplicate event/interaction
- Cross-tenant exposure
- Unexpected customer communication
- Provider rejection spike
- Reconciliation mismatch
- Worker crash loop
- p95 latency breach
- Compliance or consent failure

Rollback must preserve evidence, restore the prior immutable artifact, restore data only through the reviewed restoration procedure, verify production health and create an incident record.

---

## 20. Definition of done

Do not report completion until all required results are true:

```text
ODOO_MODULE_INSTALL=PASS
ODOO_MODULE_UPGRADE=PASS
DATA_MIGRATION=PASS
DATABASE_INTEGRITY=PASS
API_CONTRACTS=PASS
VICIDIAL_CONNECTOR=PASS
BROWSER_SCREEN_POP=PASS
AGENT_DESKTOP=PASS
CAMPAIGN_PUBLISHING=PASS
DISPOSITION_WORKFLOW=PASS
CUSTOMER_360=PASS
CLIENT_OPERATIONS=PASS
AGENT_ONBOARDING=PASS
IDENTITY_PROVISIONING=PASS
MAILBOX_PROVISIONING=PASS
COMPLIANCE_CONTROLS=PASS
SUPERVISOR_CONSOLE=PASS
QUALITY_MANAGEMENT=PASS
WORKFORCE_MANAGEMENT=PASS
CASE_MANAGEMENT=PASS
REVENUE_ASSURANCE=PASS
DATA_QUALITY=PASS
OMNICHANNEL=PASS
OUTBOX_IDEMPOTENCY=PASS
RECONCILIATION=PASS
ANALYTICS=PASS
NEGATIVE_AUTHORIZATION=PASS
BACKUP_STATUS=PASS
RESTORE_REHEARSAL_GATE=PASS
IMMUTABLE_RELEASE=PASS
SBOM=PASS
PROVENANCE=PASS
STAGING_CERTIFICATION=PASS
BOUNDED_CANARY=PASS
ONE_HOUR_SOAK=PASS
ONE_BUSINESS_DAY_SOAK=PASS
PRODUCTION_RECONCILIATION=PASS
ROLLBACK_REHEARSAL=PASS
FINAL_STATUS=PASS
```

If an external approval or provider capability remains unavailable, report the exact item as `BLOCKED`. Do not misrepresent a partially enabled channel as production-ready.

---

## 21. Final Codex report format

```text
BASELINE_COMMIT=
FINAL_PROTECTED_COMMIT=
RELEASE_IMAGE_DIGEST=
ODOO_VERSION=
MODULES_CREATED=
MODULES_UPGRADED=
MIGRATIONS_APPLIED=
DATABASE_RECORD_RECONCILIATION=
API_ENDPOINTS_IMPLEMENTED=
OPENAPI_STATUS=
TESTS_PASSED=
TESTS_FAILED=
SCREEN_POP_P95=
EVENT_PROCESSING_P95=
LOAD_TEST=
SECURITY_SCAN=
SECRET_SCAN=
SBOM_STATUS=
PROVENANCE_STATUS=
BACKUP_EVIDENCE=
RESTORE_EVIDENCE=
STAGING_EVIDENCE=
CANARY_EVIDENCE=
ONE_HOUR_SOAK=
ONE_BUSINESS_DAY_SOAK=
ACTIVATED_CAMPAIGNS=
ACTIVATED_CHANNELS=
DISABLED_CHANNELS=
ROLLBACK_STATUS=
PRODUCTION_STATUS=
FINAL_STATUS=
BLOCKERS=
NEXT_SAFE_ACTION=
```

Include links to protected PRs, workflow runs, releases and evidence. Never include secrets or private credential material.
