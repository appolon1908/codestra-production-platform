# Draft Pull-Request Review — 2026-09-02

## Scope

This review covers every pull request returned by the repository's open-draft query
at the review boundary. The protected source baseline was
`f1788b0bc7b15d210ddb191bb0a6e9151b8ab59d`.

Twenty-one drafts were classified by source lineage, changed-file scope, exact-head
checks, review threads, supersession, and runtime safety.

## Promotion decision

The following isolated extensions are recovered onto the current protected lineage:

- PR #126 — versioned, replay-safe completed-call RPC API;
- PR #128 — snooze, contextual actions, and resilient agent UX;
- PR #131 — durable, disabled-by-default middleware automation outbox;
- PR #155 — repository profile, rewritten to match actual authority.

The consolidation adds additional review remediations:

- a 65,536-byte API request bound;
- strict API-version and customer-email validation;
- credential-free HTTPS enforcement and secret-safe client representation;
- `FOR UPDATE SKIP LOCKED` snooze release;
- no-follow, descriptor-bound secret-file reads;
- rejection of query-bearing automation target URLs;
- one disposable Odoo 19 integration gate for the core and all promoted extensions.

## Closure decision

Legacy stacked branches, duplicate implementations, obsolete architecture snapshots,
and release packages tied to superseded SHAs are closed without merging. Their branch
history remains available, and unique deferred capabilities are recorded in
`config/draft-pr-disposition-2026-09-02.json`.

Closing a draft does not claim that its runtime feature was deployed. It removes stale
source candidates from the active merge queue.

## Deferred capability backlog

The following useful capabilities require fresh current-base implementation rather
than direct draft merges:

- auditable native Odoo mail-delivery evidence and recovery from PR #121;
- server-authoritative multi-tab popup leases from PR #122;
- SLA and missed-callback automation from PR #123;
- read-only call-followup analytics from PR #124.

## Production boundary

```text
SOURCE_REVIEW=COMPLETE
RUNTIME_DEPLOYMENT=NO
DATABASE_MIGRATION=NO
ODOO_MODULE_INSTALLATION=NO
REMOTE_AUTOMATION_ENABLED=FALSE
LIVE_EMAIL=NO
LIVE_SMS=NO
LIVE_PSTN=NO
CAMPAIGN_ACTIVATION=NO
SSH_CHANGED=NO
```

A protected source merge remains separate from staging, immutable artifact
publication, backup/restore rehearsal, canary authorization, and production readback.
