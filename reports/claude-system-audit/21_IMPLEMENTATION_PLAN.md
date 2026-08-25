# 21 — Implementation Plan (PLANNING ONLY — no Phase 2 work has begun)

This is a proposed sequencing for remediation, provided for human review and authorization. Per the mission's explicit rule, **no implementation begins from this audit** — this document exists so that whoever authorizes Phase 2 can approve, reorder, or reject each phase deliberately.

## Phase A — Security P0s (independent, low-blast-radius, do first)

Each of these is isolated and doesn't depend on anything else in this plan.

1. `VIC-P0-01` — fix `vicidial_auth_entries.txt` permissions on the VICIdial host; inspect contents with root access first to know if credential rotation is also needed.
2. `AST-P0-02` — read `http.conf` with root access on the VICIdial host, scope Asterisk's HTTP management server to the private VLAN.
3. `NET-P0-01` — decide with the platform owner: route the Klyrow/Telnexa→middleware path through Kong, or formally document and mTLS-restrict the exception. Either way, stop leaving it as an ungoverned firewall rule.
4. `SEC-1` — a human with authorized access triages the 44+12 secret-scanner findings; rotate/purge anything real.

**Exit criteria:** all four P0s closed or explicitly accepted-risk with sign-off; re-run the secret scanner and confirm 0 unreviewed findings.

## Phase B — Release/GitHub hygiene (unblocks trustworthy Phase C-E work)

Doing this before feature work matters because otherwise Phase C-E changes land on top of an already-11-days-stale, unpinned production image.

1. `GH-03` — build/pull the correct signed digest of `Codestra-SRL/codestra-middleware` at a reconciled current commit; retire local mutable tags from any path that can reach a running container.
2. `INV-P0-01` — per-repo review of all 10 dirty server-side checkouts; commit-and-push or deliberately discard each.
3. Re-run `03_GITHUB_RUNTIME_RECONCILIATION.md`'s method against the post-fix state to confirm runtime now matches a specific, signed, reviewable commit.

**Exit criteria:** production middleware's `/version` endpoint (currently non-functional per `M-2`) reports real `source_sha`/`release_id`/`image_digest`, and that SHA is HEAD of a reviewed, signed release.

## Phase C — The two features that actually block the mission's acceptance criteria

This is the core gap. Nothing else in this plan matters to end users until this phase lands.

1. `AGENT-01` — build a real disposition/notes/callback API (middleware endpoint + Odoo write path) and replace `mockDesktopService` in the agent desktop. This is the single highest-priority code change in the entire audit.
2. `AGENT-02` — design and implement the click-to-call endpoint (`/calls/originate` or similar) with auth, campaign-permission check, E.164 validation, idempotency key, correlation ID, timeout/failure handling — plus the corresponding Odoo `crm.lead` button/action.
3. `AGENT-03` — replace the hardcoded `CAMPAIGN`/`ENDPOINT` constants in `webphone.py` with per-agent resolution, using the existing `_odoo_identity`/`_keycloak_user` lookup already in that file.
4. `AGENT-04` — expand the ACD state model to the mission's full 10-state set once the above land (state modeling is moot while the panel is mocked).

**Exit criteria:** a staging agent can take a call, save a real disposition, and see it reflected in a staging Odoo CRM record; a staging agent can click-to-call from a CRM record and see the call attempt logged end-to-end (with `LIVE_PSTN_DIALING` still `false` — verify the endpoint fails closed/no-ops correctly rather than silently "succeeding").

## Phase D — Odoo completeness

1. `ODOO-02` — install and test `codestra_telephony_bridge`, `codestra_vicidial_recording`, `codestra_interaction_workflow` in staging (each has its own test suite already — run it, not just read it).
2. `ODOO-01` — re-enable business-critical `ir_cron` jobs one at a time with a monitoring window each, or document per-job why it stays off.
3. `ODOO-03` — verify `ir.rule` record rules actually scope `crm.lead`/`res.partner` by business unit for every role, given `breero_crm` shares the same database.

**Exit criteria:** recording metadata links to CRM records in staging; cross-tenant read attempt (Codestra role against Breero data, and vice versa) is correctly denied.

## Phase E — Email architecture fix (the one channel that's wrong, not just gated)

1. `EMAIL-P1-01` — route Odoo's outbound mail through the middleware's email adapter, or make the direct-to-Klyrow path an explicit, documented, audited exception with correlation IDs.
2. `EMAIL-P1-02` — re-enable Odoo's mail-queue-flush cron once the routing decision above is made.
3. Cross-reference `13_N8N.md`'s inactive `MailBounceV1`/`MailComplaintV1`/`MailDeliveryStatusV1`/`InboundMailReceivedV1`/`MailReconciliationV1` workflows — these are the bounce-loop half of this same fix, sequence with Phase G below.

**Exit criteria:** a staging test email traces through middleware→adapter→(mock/staged provider), with a correlation ID and audit event, not direct Odoo→SMTP.

## Phase F — Observability restoration

1. `OBS-P1-01` — restart Prometheus; add a meta-monitoring check (external heartbeat or blackbox probe of Prometheus's own health) so this specific failure mode isn't silent again.
2. `OBS-P2-01` — stand up Grafana or confirm/document that `codestra-monitoring-receiver-receiver-1` already substitutes for it.
3. `OBS-P3-01` — add a NATS Prometheus exporter, since middleware workers may depend on NATS and its queue depth is currently invisible.

**Exit criteria:** Alertmanager shows active routes fed by live scrape data; a synthetic "kill a container" test produces a visible alert.

## Phase G — Backup/DR reactivation

1. `BKP-P1-02` — determine why the restore-validation pipeline stopped running in early August (likely tied to the same trigger as the inert `codestra-readiness-*` timers found in `01_RUNTIME_INVENTORY.md`); re-enable and confirm a fresh evidence bundle.
2. `BKP-P1-01` — decide what `server-b-essential.enc` actually is; either put it on a recurring cadence or relabel/relocate it so it's not mistaken for a live DR artifact.

**Exit criteria:** a restore-validation run completes end-to-end and produces a dated evidence bundle less than 7 days old.

## Phase H — n8n staged activation (sequence after Phase C-E, not before)

Activating automation before the features it automates around are fixed just automates the current broken behavior faster. Do this last among the functional-gap phases.

1. Define the "isolated gate" criteria the workflow repo's README already references for exiting Sprint 1.
2. Activate in controlled batches, starting with `N8-00 Global Error Handler` / `WF-90_ERROR_AND_DEAD_LETTER`, then one business vertical at a time, each verified in the existing `codestra-n8n-staging` stack first.

**Exit criteria:** each activated workflow class has before/after evidence showing it performs the real business operation, not just logs an event.

## Phase I — Go-live decision (Category A gates)

Only after Phases C, D, E are verified in staging: a deliberate, owner-approved decision to flip `LIVE_SMS_DELIVERY`/`LIVE_EMAIL_DELIVERY`/`LIVE_PSTN_DIALING`, in that order, each with a defined rollback trigger and a monitoring window (which requires Phase F to already be done).

## Phase J — Hygiene (parallelizable with anything above, no urgency)

`docker system prune` review, compose-file consolidation, stale network cleanup, `codestra-cp-candidate-api` crash-loop resolution, `codestra-websocket-standby-031447a` startup fix, container/service renaming for clarity (`M-3`, `DB-3`), and a general sweep of the ~150 untracked "evidence" scratch directories (`SEC-4`).

---

**Recommended sequencing:** A → B → C (the real work) → D/E in parallel → F/G in parallel → H → I, with J running in the background throughout. Phases C through E are the actual path to a working product; everything else is either safety (A, F, G) or de-risking the path to flipping the switches (B, I).
