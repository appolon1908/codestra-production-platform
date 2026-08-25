# 00 — Executive Summary

**Audit date:** 2026-08-25
**Scope:** `codestra-app` (65.109.65.169, hostname `middleware`) + read-only SSH to `codestra-vicidial` (10.40.0.2). `codestra-provider` (10.40.0.4, Telnexa/Klyrow) and `codestra-scraper` (10.40.0.3) excluded per explicit user scoping decision.
**Method:** 8 parallel read-only investigations across 25 mission steps, evidence-based (`docker inspect`, source reads, live API probes, DNS lookups, SQL SELECTs, systemd/journal state). No service was restarted, no config changed, no call/SMS/email sent, no branch merged.

## Bottom line

**PRODUCTION_READY = NO.**

This is not a borderline call. Two of the mission's explicit, named acceptance requirements fail at the *code* level — not behind a feature flag, not "needs configuration," but literally absent or actively discarding data:

- **Click-to-call from Odoo does not exist.** No endpoint in the middleware, no action method on the Odoo CRM lead model. (Step 5 requirement — see `AGENT-02`, P0)
- **The agent desktop's disposition/notes/callback save actions are hardcoded no-ops** (`mockDesktopService`) that report success to the agent while discarding the input. Nothing an agent does after a call reaches Odoo's CRM. (Step 4 requirement — see `AGENT-01`, P0)

On top of that, the entire platform is currently **behind an intentional, fail-closed kill switch**: every middleware container, the SMS API, and n8n all refuse to place a live call, send a live SMS, or send a live email unless three environment flags (`LIVE_SMS_DELIVERY`, `LIVE_EMAIL_DELIVERY`, `LIVE_PSTN_DIALING`) are exactly `false` — and they are, everywhere, right now. This looks like deliberate, well-engineered pre-production safety work, not an accident — but it means no external communication can happen today regardless of what else is fixed.

## What's actually good (don't let the blocker list obscure this)

- **The core architectural boundaries the mission cares most about genuinely hold.** Odoo has no direct VICIdial database driver import anywhere in its deployed addon code; no n8n workflow uses a database node pointed at VICIdial; no database port is reachable from a browser or the public internet. Verified by reading actual deployed code, not trusting docs. (`14_DATABASES.md`)
- **The middleware application code itself is well-engineered.** Zero TODO/FIXME/NotImplementedError/stub bodies across 76 source files. Real idempotency table, outbox pattern, dead-letter replay, HMAC-verified webhooks with TTL, a circuit breaker, and global bearer auth are all genuinely implemented, not placeholders. (`07_MIDDLEWARE.md`, M-6)
- **SMS infrastructure is the best-engineered of the communication channels** — idempotent DLR handling with row locking, dead-letter table, fail-closed state checks — just intentionally not live yet. (`12_SMS.md`)
- **VICIdial/Asterisk are real, running production telephony**, not scaffolding — Asterisk 18.26.4-vici, 9-day uptime, correctly narrow read-only adapters instead of direct DB access from Odoo/n8n. (`06_VICIDIAL_ASTERISK.md`)
- **Inbound screen-pop's notification mechanism is real and working**: a genuine `call.ringing` WebSocket event drives a popup with a correct deep link into the Odoo lead record, with proper reconnect handling. It's the single strongest piece of the agent-facing call experience — it just currently pops up in front of a CRM panel that can't save anything. (`05_AGENT_DESKTOP_AND_WEBRTC.md`)

## The seven P0 findings

| ID | Component | One-line |
|---|---|---|
| `AGENT-01` | Agent Desktop | Disposition/notes/callback UI is a mocked no-op; agents see false success while data is silently discarded |
| `AGENT-02` | Middleware / Odoo | No click-to-call endpoint or Odoo action exists anywhere in code |
| `GH-03` | Release engineering | Production middleware runs a locally-tagged, mutable image 219 commits (~11 days) behind `main`, outside the documented signed-release pipeline |
| `INV-P0-01` | GitHub/runtime drift | None of 12 resolvable server-side repo checkouts are on `main`; 10/12 are dirty — runtime cannot be reconstructed from GitHub alone |
| `NET-P0-01` | Network / Kong boundary | Firewall lets the explicitly out-of-scope Klyrow/Telnexa host reach the middleware's main API directly, bypassing Kong entirely |
| `VIC-P0-01` | VICIdial host | World-writable (`777`) auth-named file sitting in the internet-facing Apache web root |
| `AST-P0-02` | Asterisk host | Asterisk's built-in HTTP management server bound to `0.0.0.0` on a publicly-addressed host, unlike AMI (correctly loopback-only) |

## Coverage gap — read before trusting "VICIdial is fine"

The audit account on `codestra-vicidial` has **no sudo and isn't in the `asterisk`/`mysql`/`systemd-journal` groups**. Campaigns, users, DIDs, dial ratios, recording retention, the full VICIdial↔Odoo mapping, and Asterisk's dialplan/trunk/queue config are all **UNVERIFIED**, not confirmed-clean. Treat VICIdial/Asterisk's deep configuration as an open question, not a pass, until someone with legitimate admin access runs a scoped export. (`VIC-P1-04`)

## Themes that cut across multiple systems

1. **The platform's automation layer is switched off by explicit, documented policy, not broken.** 129 of 130 n8n workflows are inactive per a "Sprint 1" gating policy in the workflow repo's own README. Nearly all of Odoo's lead/callback/SLA/email/SMS cron jobs are `active=false`. This is consistent, deliberate, and cuts across Odoo, n8n, and the SMS/email kill switches — read as one coordinated pre-launch posture, not five unrelated gaps.
2. **Email is the one channel that's architecturally wrong, not just gated.** Odoo sends mail directly to an external SMTP relay (`mail.klyrow.com`) owned by a different, explicitly out-of-scope product — never touching the middleware at all — and even that direct path's own queue-flush cron is disabled. (`EMAIL-P1-01`, `EMAIL-P1-02`)
3. **A readiness/validation subsystem appears to have quietly stopped in early August.** The restore-validation pipeline (HMAC + cosign, staged scripts) hasn't produced evidence in 24 days; three `codestra-readiness-*` timers went inert around the same time; Prometheus is stopped with nothing to notice. Someone should confirm whether this was a deliberate pause or a silent regression.
4. **Heavy, unsupervised remediation churn has left the host cluttered but not unsafe.** 234 Docker containers (most exited test/canary/rollback artifacts), 100+ throwaway directories, 50+ compose files, dozens of stale networks — almost all dated around one apparent large automated sweep on 2026-08-22. Confirmed nothing live depends on the debris, but it materially slows down every audit and incident response that follows.

## Report index

| # | File | Steps covered |
|---|---|---|
| 01 | `01_RUNTIME_INVENTORY.md` | 1 |
| 02 | `02_NETWORK_MATRIX.md` | 19 |
| 03 | `03_GITHUB_RUNTIME_RECONCILIATION.md` | 2 |
| 04 | `04_ODOO_READINESS.md` | 3 |
| 05 | `05_AGENT_DESKTOP_AND_WEBRTC.md` | 4-8 |
| 06 | `06_VICIDIAL_ASTERISK.md` | 9-10 |
| 07 | `07_MIDDLEWARE.md` | 11 |
| 08 | `08_KONG.md` | 12 |
| 09 | `09_CADDY.md` | 13 |
| 10 | `10_IDENTITY.md` | 14 |
| 11 | `11_EMAIL.md` | 15 |
| 12 | `12_SMS.md` | 16 |
| 13 | `13_N8N.md` | 17 |
| 14 | `14_DATABASES.md` | 18 |
| 15 | `15_SECURITY.md` | 24 |
| 16 | `16_OBSERVABILITY.md` | 20 |
| 17 | `17_BACKUP_DR.md` | 21 |
| 18 | `18_API_ENDPOINT_MATRIX.md` | 22 |
| 19 | `19_END_TO_END_CALL_FLOW.md` | 23 |
| 20 | `20_PRODUCTION_BLOCKERS.md` | synthesis |
| 21 | `21_IMPLEMENTATION_PLAN.md` | synthesis |

## Severity totals

**P0: 7 · P1: 16 · P2: 22 · P3: 21** (66 findings total across all 18 detail reports)
