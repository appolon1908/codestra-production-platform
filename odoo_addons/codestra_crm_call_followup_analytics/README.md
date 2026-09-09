# Codestra CRM Call Follow-up Analytics — Odoo 19

This optional addon provides read-only operational reporting for the core call-follow-up workflow.

## Why this is separate

Dashboards, pivots, graphs, and aggregate APIs can become expensive at scale. The addon therefore uses a dedicated SQL view and can be deployed, tuned, or removed without changing the transaction that records a completed call.

## Metrics

- total, pending, completed, and cancelled calls;
- post-call completion time and SLA buckets;
- pending records older than 10 minutes;
- callback and appointment rates;
- callback lead time;
- immediate email queued, sent, failed, or cancelled;
- agent scorecards;
- daily, weekly, and monthly grouping;
- company, outcome, schedule, status, email, and completion-SLA filters.

## API model

`codestra.crm.call.followup.analytics.api`

- `capabilities_v1()`
- `summary_v1(date_from=None, date_to=None, company_ids=None, agent_ids=None)`
- `agent_scorecards_v1(date_from=None, date_to=None, company_ids=None, agent_ids=None, limit=100)`

The APIs are read-only and manager-restricted. Requested companies are intersected with the current user's allowed companies.
An explicit empty company list is denied. Filters accept at most 500 positive integer
IDs per list and an inclusive date window of at most 366 days. The default remains
30 days. Each aggregate SQL query has a five-second timeout, preserving any stricter
operator timeout. A cancelled query rolls back its savepoint and restores the prior
timeout without aborting the surrounding transaction. These limits are exposed by
`capabilities_v1()`; they are query bounds, not a production latency guarantee.

## Metric definitions

- **Completion minutes:** `popup_completed_at - ended_at`, never below zero.
- **Completed within five minutes:** completed records whose completion interval is at most five minutes.
- **Pending over ten minutes:** pending records whose call ended more than ten minutes before the query.
- **Callback rate:** callback records divided by total scoped records.
- **Appointment rate:** appointment records divided by total scoped records.
- **Email failed:** linked Odoo mail in `exception` state.

## Safety and scale

- The report model is `_auto = False` and all ACLs are read-only.
- Agents see only their records; managers see permitted-company records.
- No controller, external provider call, direct telephony write, or data copy is introduced.
- The operational view is intentionally not materialized in this first release. Query plans and production row counts must be reviewed before adding materialization or additional indexes.

## Runtime acceptance

- SQL view installs and upgrades cleanly on Odoo 19/PostgreSQL;
- agent and manager record rules pass;
- API date and company scopes pass;
- KPI values reconcile to source records;
- pivot and graph views open without write permission;
- explain plans are captured on staging-scale data;
- dashboards do not materially increase Odoo request latency or database load.
