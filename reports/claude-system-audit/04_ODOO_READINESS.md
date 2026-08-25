# 04 — Odoo 19 Readiness

Scope: Steps 3 (Odoo 19 deployment) + the VICIdial/Odoo integration module review, on host `codestra-app` (this host), container `codestra-odoo-1`. Read-only. All evidence gathered via `docker inspect`, `docker exec`, direct source read, and one read-only `psql` query against `codestra_odoo`.

## Summary

Odoo 19.0-20260630 is running as a single production container (`codestra-odoo-1`, healthy) with 24 custom Codestra modules installed. Code quality is good (zero TODO/FIXME/NotImplementedError hits across the six modules sampled). However, **the entire live-traffic surface is administratively fail-closed by design** — a large, consistent set of environment flags and disabled cron jobs — and **one integration module central to click-to-call (`codestra_telephony_bridge`) is present in source but not installed**, along with `codestra_vicidial_recording` and `codestra_interaction_workflow`.

## Evidence

### Deployment
- Image: `odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`, built 2026-08-23T02:38:31Z.
- `odoo --version` → `Odoo Server 19.0-20260630`.
- Entrypoint: `/usr/local/bin/odoo-secret-entrypoint.sh` (custom secret-resolving wrapper, not stock Odoo).
- Runtime flags (from `docker inspect .Config.Cmd`): `--workers=4 --max-cron-threads=1 --gevent-port=8072`. `proxy_mode = True` (correct behind Caddy), `http_port=8069`, `longpolling_port=8072` (bus/WebSocket for real-time UI updates — configured).
- **Addons-path drift**: the container CLI overrides `odoo.conf`'s `addons_path`. Actual runtime path = `dist-packages/odoo/addons, /mnt/integration-addons, /mnt/call-center-addons, /mnt/breero-addons`. `odoo.conf` itself still declares `addons_path = .../mnt/extra-addons,/mnt/shared-inbox-addons` — `/mnt/shared-inbox-addons` isn't mounted at all, and `/mnt/extra-addons` (which is mounted and contains a *different, overlapping* set of module copies) is never actually on the effective path because the CLI arg wins. This is config drift that would confuse any operator reading `odoo.conf` to understand what's live.
- DB: `codestra_odoo` on `codestra-postgres-1`, user `odoo_app`, password sourced from Docker secret file (not env var — good practice).

### Installed modules (verified via `ir_module_module`, not assumed from source tree)
92 modules installed. Custom/call-center relevant ones installed: `codestra_base`, `codestra`, `codestra_vicidial_crm` (3.0.0), `codestra_vicidial_connector`, `call_center_core`, `call_center_campaign`, `call_center_compliance`, `call_center_lead_validation`, `call_center_orchestration`, `codestra_ivr_control`, `codestra_ai_core/_qualification/_call_audit/_realtime_assistant/_review`, `codestra_transcription`, `codestra_analytics_reporting`, `codestra_daily_reporting`, `codestra_appointments`, `codestra_identity_provisioning`, `codestra_integration_hub`, `codestra_middleware_bridge`, `codestra_campaign_crm_os`, `codestra_mail_inbox`, `codestra_lead_ingestion`, `codestra_odoo_certification`, `breero_crm` (a *different* product's CRM module, also installed in the same DB — see finding ODOO-03).

**Modules present in the `/mnt/call-center-addons` source tree but NOT installed:**
| Module | State |
|---|---|
| `codestra_telephony_bridge` | `uninstalled` |
| `codestra_vicidial_recording` | `uninstalled` |
| `codestra_interaction_workflow` | `uninstalled` |
| `codestra_lead_automation` | `uninstalled` |
| `codestra_staging_campaign_design` | `uninstalled` |

`codestra_telephony_bridge`'s manifest summary is *"Odoo-owned telephony desired state and reconciliation projections"* — this reads as the intended home for exactly the kind of state Step 4/23 requires (agent/campaign/extension desired-state tracking), and it is not active.

### Scheduled jobs (`ir_cron`, verified via SQL)
Of 38 cron jobs, the ones governing the actual lead/call/comms pipeline are **disabled** (`active = false`):
- `CRM: Lead Assignment` — disabled
- `Campaign Appointment Reminders` — disabled
- `Campaign SLA Escalation` — disabled
- `Codestra Callback Reminder and Escalation` — disabled
- `Codestra retry eligible events (disabled)` — disabled (name states it explicitly)
- `Integration Hub: retry eligibility report (disabled)` — disabled (ditto)
- `Lead Ingestion: Metrics Aggregation / Process Import Chunks / Process Pending Batches / Reconciliation Polling / Retention Cleanup / Stale Batch Alerts` — **all six disabled**
- `Mail: Fetchmail Service`, `Mail: Email Queue Manager` — disabled
- `SMS: SMS Queue Manager` — disabled

Only enabled: `Codestra callback middleware reconciliation` (5 min), `Codestra callback middleware sync` (1 min), plus generic Odoo housekeeping (HR notify, mail marketing queue, website visitor cleanup, snippet cleanup).

### Runtime kill-switch environment variables (verified via `docker inspect .Config.Env`, redacted)
```
EXTERNAL_DIAL_ENABLED=false
ALLOW_LIVE_CALLS=false
ALLOW_LIVE_SMS=false
ALLOW_LIVE_EMAIL=false
TRANSFERS_ENABLED=false
PRODUCTION_CALLBACKS_ENABLED=false
SEND_EVENTS=false
VICIDIAL_WRITES_ENABLED=false
WEBRTC_PRODUCTION_ROUTES_ENABLED=false
ALLOW_CAMPAIGN_ACTIVATION=false
N8N_PRODUCTION_WORKFLOWS_ENABLED=false
CODESTRA_CALLBACK_ALLOWED_TENANT=COD
CODESTRA_CALLBACK_ALLOWED_CAMPAIGN=TEST_SYN
```
Every flag governing live external effect is `false`. `CODESTRA_CALLBACK_ALLOWED_CAMPAIGN=TEST_SYN` further scopes the one thing that *is* enabled (`CODESTRA_CALLBACK_SYNC_ENABLED=true`) to a synthetic test campaign only.

### Identity / auth
`CODESTRA_ODOO_KEYCLOAK_ISSUER=https://auth.codestra.co/realms/codestra` and a JWKS URL are configured, and `codestra_identity_provisioning` is installed — but no stock `auth_oidc` Odoo module is installed, so SSO is implemented via the custom `codestra_identity_provisioning` module rather than Odoo's built-in OIDC. Not independently verified end-to-end (would require an interactive login, out of scope for Phase 1); marked UNVERIFIED for actual login flow correctness.

### VICIdial/Odoo integration module code quality
`codestra_vicidial_crm/models/crm_lead.py`: extends `crm.lead` with a full set of VICIdial correlation fields (`x_vicidial_lead_id`, `x_last_call_uniqueid`, `x_last_call_disposition`, `x_sync_status`, `correlation_id`, E.164 normalization helper, computed `call_count` via `codestra.vicidial.call` model). This is real, non-trivial modeling — not a stub.
`call_center_orchestration/models/orchestration.py:action_approve_vicidial_sync()` — the lead-approval action that would push a lead into VICIdial explicitly sets `sync_state: "queued_disabled"` rather than performing a sync. This is intentional code-level gating, consistent with `VICIDIAL_WRITES_ENABLED=false` — i.e., the *write path* to VICIdial is disabled both by env flag and by the state value the code itself writes.

## Findings

**ODOO-01 (P1)** — Component: Odoo / call pipeline automation. The lead-assignment, callback-reminder, SLA-escalation, lead-ingestion (×6), fetchmail, email-queue, and SMS-queue cron jobs are all `active=false` in production `ir_cron`. Expected: an Odoo instance claiming production readiness runs its own business-critical automation. Current: only 2 of ~10 relevant automations run (callback middleware sync/reconciliation). Risk: leads will not be auto-assigned, SLA breaches won't be escalated, callbacks won't be reminded, inbound email/SMS won't be processed into Odoo even if the upstream systems deliver them. Files: `ir_cron` table, `codestra_odoo` DB. Fix: enable each job deliberately, one at a time, with a monitoring window, or document why each is intentionally off (test env vs true blocker). Test: verify each job's model method runs cleanly against a rehearsal DB before flipping `active=true` in prod. Rollback: `active=false` again. Repo: `codestra-production-platform` (addons under `/opt/codestra/odoo-addons`, GitHub path TBD — see 03_GITHUB_RUNTIME_RECONCILIATION). Suggested branch: `fix/odoo-cron-activation-plan`.

**ODOO-02 (P1)** — Component: Odoo / VICIdial integration completeness. `codestra_telephony_bridge` (desired-state/reconciliation for telephony), `codestra_vicidial_recording` (recording metadata association — required by Step 4/mission), and `codestra_interaction_workflow` are present in the source tree mounted into the container but **not installed** in the production database. Expected: recording metadata and telephony desired-state tracking function per the mission's required agent-call-flow. Current: these capabilities do not run at all in production, regardless of the `false` kill-switches — the code path can't even execute. Risk: no recording-metadata linkage to CRM records is possible today even if calling were turned on. Files: `/opt/codestra/releases/odoo-addons/91e22ef4e69e624142bb3865b16c43a14e8b69d6/{codestra_telephony_bridge,codestra_vicidial_recording,codestra_interaction_workflow}`. Fix: install and test these modules in staging before considering any go-live. Test: module install + `tests/` suite in `codestra_telephony_bridge` (its own `tests/` dir exists, 3 test files, ~470 lines — run it). Rollback: uninstall. Repo/branch: same as above, `feat/install-telephony-bridge-module`.

**ODOO-03 (P2)** — Component: Odoo / tenant isolation. `breero_crm` (a module for the unrelated "Breero" home-services product — confirmed via GitHub repo list) is installed in the *same* `codestra_odoo` database as the Codestra call-center modules. Expected (per mission architecture): clear tenant/business-unit boundaries. Current: two distinct businesses share one Odoo database/instance. Risk: cross-tenant data exposure via shared `res.partner`/`crm.lead` tables unless record rules strictly scope by `business_unit`, and a bug or overly broad `ir.rule` in one product's module can leak the other's data. Fix: verify `ir.rule` record rules on `crm.lead`/`res.partner` actually scope by business unit for every role (not verified in this pass — recommend a dedicated check). Files: `ir_module_module` (breero_crm), `ir.rule` definitions across installed modules. Test: attempt cross-tenant read as a Breero-scoped user against Codestra call-center records (and vice versa) in a non-prod clone. Rollback: n/a (observational). Repo: unclear which repo owns `breero_crm`'s source — flag for 03_GITHUB_RUNTIME_RECONCILIATION.

**ODOO-04 (P3)** — Component: Odoo / config hygiene. `odoo.conf`'s `addons_path` doesn't match the addons path actually in effect (CLI arg override). Risk: low (functionally the CLI wins) but high operator-confusion risk during incident response. Fix: make `odoo.conf` match reality, or remove the conflicting `addons_path` line and rely solely on the documented CLI invocation. Files: `/opt/codestra/config/odoo/odoo.conf`. Repo/branch: `chore/odoo-conf-addons-path-consistency`.

## Status: UNVERIFIED items
- End-to-end Keycloak SSO login flow (would require interactive session).
- `ir.rule` record-rule correctness for tenant isolation (ODOO-03) — flagged, not fully audited in this pass due to scope.
- Backup/restore evidence for the Odoo DB/filestore specifically — deferred to `17_BACKUP_DR.md` (different audit stream) to avoid duplicate work; cross-reference there.
