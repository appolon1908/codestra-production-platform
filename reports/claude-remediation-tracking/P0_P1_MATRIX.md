# P0/P1 Remediation Tracking Matrix

Master branch: `hardening/production-ready-20260825` (created in `codestra-production-platform`, `Codestra-SRL/codestra-middleware`, `Codestra-SRL/codestra-odoo-addons`)

Status values: OPEN → IMPLEMENTING → IMPLEMENTED → TESTED → VERIFIED → CLOSED

## P0 (7)

| ID | Component | Status | Repo | Branch | Commit | PR | Notes |
|---|---|---|---|---|---|---|---|
| AGENT-01 | Agent Desktop disposition persistence | IMPLEMENTED, CI green, awaiting human review | Codestra-SRL/codestra-middleware + codestra-odoo-addons | hardening/odoo-agent-persistence | a8ad794/07c9ea8 (mw), 250a3be (odoo) | mw#264, odoo#51 | Odoo-side tests written but not executed against live Odoo; interaction_result_hmac_secret needs ops provisioning |
| AGENT-02 | Click-to-call | IMPLEMENTED, mw CI green pending sqlite fix merge, awaiting human review | Codestra-SRL/codestra-middleware + codestra-odoo-addons | hardening/production-ready-20260825 | 80e4066+4e1426c (mw), e0ac5f2 (odoo) | mw#263, odoo#50 | Fails closed via 3 layers; VICIdial-side counterpart endpoint not yet built (separate scope) |
| (unplanned) | Repo-wide CI Docker build broken (stale pinned sqlite apk) | IMPLEMENTED | Codestra-SRL/codestra-middleware | fix/pinned-sqlite-apk-404 | 53aee88 | mw#265 | Blocks all PRs' CI until merged; discovered while verifying AGENT-01/02 |
| GH-03 | Release drift — prod middleware 219 commits behind | OPEN | Codestra-SRL/codestra-middleware | hardening/release-reconciliation | — | — | Needs signed digest rebuild |
| INV-P0-01 | Server-side git drift (10/12 dirty checkouts) | OPEN | multiple | hardening/release-reconciliation | — | — | Per-repo triage |
| NET-P0-01 | Firewall bypass — Klyrow/Telnexa direct middleware access | OPEN | codestra-production-platform (infra) | hardening/kong-caddy-network | — | — | Now in-scope per user decision; route through Kong or mTLS |
| VIC-P0-01 | World-writable auth file in VICIdial web root | OPEN | n/a (server file) | hardening/vicidial-asterisk | — | — | Trivial chmod fix |
| AST-P0-02 | Asterisk HTTP bound 0.0.0.0 | OPEN | n/a (server config) | hardening/vicidial-asterisk | — | — | Needs http.conf read first |

## P1 (16)

| ID | Component | Status | Branch | Notes |
|---|---|---|---|---|
| AGENT-03 | Hardcoded webphone campaign/endpoint | OPEN | hardening/agent-session-state | |
| ODOO-01 | Disabled business-critical cron jobs | OPEN | hardening/odoo-agent-persistence | |
| ODOO-02 | telephony_bridge/vicidial_recording/interaction_workflow uninstalled | OPEN | hardening/odoo-agent-persistence | |
| VIC-P1-03 | 3 failing telephony health-check units | OPEN | hardening/vicidial-asterisk | |
| VIC-P1-04 | VICIdial deep config UNVERIFIED (access gap) | OPEN | hardening/vicidial-asterisk | Needs scoped elevated access |
| KONG-01 | /api/v1/admin/mail missing OIDC plugin | OPEN | hardening/kong-caddy-network | |
| CADDY-01 | phone.codestra.agency missing auth gate | OPEN | hardening/kong-caddy-network | |
| EMAIL-P1-01 | Odoo bypasses middleware, direct SMTP to Klyrow | OPEN | hardening/email | Klyrow now in-scope |
| EMAIL-P1-02 | Odoo mail queue cron disabled | OPEN | hardening/email | |
| SEC-1 | 44+12 unreviewed secret-scanner findings | OPEN | hardening/secrets-hygiene | |
| OBS-P1-01 | Prometheus down, monitoring blind | OPEN | hardening/observability | |
| BKP-P1-01 | Cross-host DR archive 32 days stale | OPEN | hardening/backup-dr | |
| BKP-P1-02 | Restore-validation pipeline silent 24 days | OPEN | hardening/backup-dr | |

(SMS-P1-01 and N8N-P1-01 are Category-A intentional gates per `20_PRODUCTION_BLOCKERS.md`, not defects — tracked separately as "bring to ready-but-disabled state," not "fix.")

## Directly-related P2s pulled in to make P0/P1 fixes production-safe

| ID | Reason pulled in |
|---|---|
| AGENT-04 | ACD state model — needed once AGENT-01 lands |
| DB-1, DB-2 | Shared superuser / no TLS — needed for database-security hardening branch |
| M-1 | Fleet running divergent commits — same fix as GH-03 |
| OBS-P2-01 | Grafana absence — needed to make OBS-P1-01 fix meaningful |
