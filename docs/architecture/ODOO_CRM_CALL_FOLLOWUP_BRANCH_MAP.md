# Odoo CRM Call Follow-up Branch Ownership

Heavy capabilities are intentionally separated so one failure domain cannot silently ride inside an unrelated CRM change.

## Stack

```text
feature/odoo19-crm-call-followup-final-20260826
        │
        └── feature/odoo19-crm-call-followup-core-hardening-v2
                ├── feature/odoo19-crm-call-followup-realtime-lease
                ├── feature/odoo19-crm-call-followup-delivery-outbox
                ├── feature/odoo19-crm-call-followup-supervisor-analytics
                └── ops/odoo19-crm-call-followup-docker-release
```

Every child branch targets the core hardening branch as a stacked pull request. A heavy branch must not be merged before its parent is accepted. After the parent merges, retarget the child to the new reviewed base and repeat affected checks.

## Core hardening branch

Owns only:

- versioned authenticated Odoo RPC contract;
- request and response schemas;
- company-scoped idempotency and conflicting-replay rejection;
- call timeline and payload bounds;
- post-call completion row lock;
- core CRM fields;
- agent form and call-to-action polish;
- callback/calendar synchronization;
- current Odoo mail queue integration;
- core model, access, and regression tests.

It does not own provider-specific telephony writes, external delivery engines, analytics warehouses, or container release authority.

## Real-time lease branch

Owns:

- cross-tab popup claim and lease;
- lease renewal and release;
- reconnect recovery;
- stale lease reclamation;
- browser/service tests and metrics.

It must not change email delivery, reporting, or Docker release code.

## Delivery outbox branch

Owns:

- auditable email/notification delivery records;
- idempotent dispatch keys;
- retry/backoff/dead-letter state;
- delivery worker/cron behavior;
- delivery operations views and tests.

It must not contain realtime popup code or supervisor analytics.

## Supervisor analytics branch

Owns:

- read-only SLA and outcome reporting;
- overdue/compliance queues;
- supervisor KPI views;
- reporting performance tests.

It must not perform call, email, calendar, or carrier mutations.

## Docker release branch

Owns:

- immutable addon image build;
- Docker health checks;
- Compose image overlay;
- database/filestore preflight;
- module upgrade entrypoint;
- Codex staging, canary, production, and rollback runbook.

It must not change business behavior in the Odoo addon.

## Merge rules

- All pull requests remain draft until their own evidence is attached.
- No branch may claim another branch's tests.
- No heavy branch may be squash-copied into the core branch.
- Deploy only a reviewed merged SHA and immutable image digest.
- Never enable production dialing, external delivery, or carrier writes as part of this module release.
- Any base or head movement invalidates prior independent approval and affected evidence.
