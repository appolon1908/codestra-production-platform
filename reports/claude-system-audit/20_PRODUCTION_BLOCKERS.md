# 20 — Production Blockers

Every P0 and P1 finding from the 18 detail reports, organized by whether it's a genuine defect to fix or an intentional gate to deliberately open. This distinction matters: treating an intentional safety gate as a "bug" risks someone flipping it without the sign-off it's there to force; treating a real defect as "just a flag" risks shipping broken functionality the moment the flag flips.

## Category A — Intentional pre-production gates (not defects; require a go-live decision, not a code fix)

These are working as designed. Nothing here should be "fixed" — each needs a deliberate, signed-off decision to open it.

| ID | Gate | What it blocks |
|---|---|---|
| — | `live-delivery-admission.sh` (`LIVE_SMS_DELIVERY`/`LIVE_EMAIL_DELIVERY`/`LIVE_PSTN_DIALING` must all be `false`) | Every middleware container, SMS API, and n8n refuse to start with real delivery enabled — blocks all real calls/SMS/email fleet-wide |
| `N8N-P1-01` | n8n "Sprint 1" activation policy (documented in workflow repo README) | 129/130 workflows inactive — zero live business automation |
| `ODOO-01` | Odoo `ir_cron` jobs disabled (lead assignment, SLA escalation, callback reminders, lead ingestion ×6, mail/SMS queue managers) | Core business automation doesn't run even if upstream systems deliver |
| `SMS-P1-01` | Same kill-switch as above, SMS-specific framing | SMS is fully built and tested but not live |

**Action needed:** a single owner-approved go-live checklist that flips these in a defined order, each with a staging verification step first (staging stacks already exist for SMS, n8n, and middleware — use them).

## Category B — Real defects (require actual code/config changes, not just a flag flip)

### P0 — must fix before any go-live consideration

| ID | Component | Fix scope |
|---|---|---|
| `AGENT-01` | Agent Desktop | Replace `mockDesktopService.disposition/saveNotes/scheduleCallback` with real calls to a backend API that persists to Odoo. Currently reports false success while silently discarding data — this is the highest-priority fix in the whole audit because it's a silent-data-loss pattern, not a visible failure. |
| `AGENT-02` | Middleware + Odoo | Design and implement a `/calls/originate`-style endpoint (auth, campaign-permission check, E.164 validation, idempotency key, correlation ID) and a corresponding Odoo `crm.lead` action/button. Does not exist today. |
| `GH-03` | Release engineering | Rebuild/redeploy production middleware from a signed, digest-pinned `ghcr.io/codestra-srl/codestra-middleware` image at a reconciled, current commit — not a locally-tagged mutable image 219 commits behind `main`. |
| `INV-P0-01` | Server-side git hygiene | Per-repo human review of all 10 dirty checkouts under `/opt/codestra` — classify each diff as config drift, an undeployed fix, or debug leftover; commit/push or discard deliberately. |
| `NET-P0-01` | Network / firewall | Remove or properly govern the UFW rule letting the out-of-scope Klyrow/Telnexa host reach the middleware's port 8095/18080 directly, bypassing Kong. Either route through Kong with real auth/rate-limiting, or require mTLS and document the exception explicitly. |
| `VIC-P0-01` | VICIdial host | Fix permissions on `/srv/www/htdocs/agc/vicidial_auth_entries.txt` (currently `777`, world-writable, sitting in a public web root); inspect its contents with root access to determine actual sensitivity. |
| `AST-P0-02` | Asterisk host | Read `/etc/asterisk/http.conf` with root access; if the HTTP management server needs to stay enabled, bind it to the private VLAN IP only and front it with a TLS reverse proxy, matching the pattern used elsewhere in the fleet. |

### P1 — must fix before declaring the platform trustworthy, even if not literally blocking

| ID | Component | Summary |
|---|---|---|
| `AGENT-03` | Middleware | Hardcoded `CAMPAIGN`/`ENDPOINT` constants mean every agent shares one SIP identity — cannot scale past one concurrent agent |
| `ODOO-02` | Odoo | `codestra_telephony_bridge`, `codestra_vicidial_recording`, `codestra_interaction_workflow` modules exist but are uninstalled — no recording-metadata linkage possible even with calling enabled |
| `VIC-P1-03` | VICIdial host | Three telephony-integration health-check systemd units are actively failing on every tick — nobody gets a reliable signal if VICIdial↔middleware connectivity breaks |
| `VIC-P1-04` | Audit coverage | VICIdial's deep configuration (campaigns/users/DIDs/dial ratios) is UNVERIFIED due to audit-account access limits — treat as an open question before declaring telephony vetted, not a pass |
| `KONG-01` | Kong | `/api/v1/admin/mail` is missing its declared `openid-connect` gateway plugin (mitigated by app-level JWT verification, but no gateway-level defense-in-depth or audit logging) |
| `CADDY-01` | Caddy | `phone.codestra.agency` (agent-desktop preview, public IP) has no auth gate on its main UI/websocket paths, unlike its production sibling `dialer.codestra.agency` which correctly requires an OAuth2 session |
| `EMAIL-P1-01` | Odoo / Email | Odoo emails bypass the middleware entirely, going direct-SMTP to an out-of-scope product's relay — no audit trail, no correlation ID, no delivery/bounce reconciliation |
| `EMAIL-P1-02` | Odoo | Odoo's own mail-queue-flush cron is disabled — even the (architecturally wrong) direct-SMTP path likely doesn't deliver automatically |
| `SEC-1` | Security | Repo's own secret scanner has 44 redacted findings + 12 sensitive/large artifacts, never triaged by a human — could be benign or could be P0, unknown until reviewed |
| `OBS-P1-01` | Observability | Prometheus is stopped; the entire metrics/alerting pipeline is currently blind with no meta-monitoring to catch that fact |
| `BKP-P1-01` | Backup/DR | The only cross-host DR archive is 32 days stale with no refresh automation |
| `BKP-P1-02` | Backup/DR | The restore-validation pipeline (HMAC + cosign, fully built) has produced no evidence in 24 days — looks like a coordinated readiness subsystem that quietly stopped in early August |

## What "PRODUCTION_READY = NO" actually rests on

If every Category A gate were flipped today with zero other changes, the platform would still fail the mission's own acceptance journeys (`19_END_TO_END_CALL_FLOW.md`): outbound calling has no entry point, and every call's outcome — inbound or outbound — is silently discarded by the agent desktop's mock CRM panel. **The Category B P0s, especially `AGENT-01` and `AGENT-02`, are the actual reason this isn't production-ready — the kill switches are just correctly preventing that from mattering yet.**
