# 18 — API Endpoint Matrix (Step 22) — Codestra Middleware only

Scope note: this matrix covers the **Codestra Middleware** application (`Codestra-SRL/codestra-middleware`, deployed as ~21 compose services on `codestra-app`), based on `origin/main` route definitions cross-checked against 2 live health probes. It does **not** cover Odoo's own controllers, Kong route definitions, the WebSocket gateway's own protocol, SMS/email provider APIs, or Keycloak — those belong in `04_ODOO_READINESS.md`, `08_KONG.md`, `11_EMAIL.md`, `12_SMS.md`, `10_IDENTITY.md` respectively and should be merged with this table by whoever assembles the final cross-system matrix.

Global auth note (applies to every row below unless stated otherwise): all `/api/*` and `/v1/*` paths are gated by a shared-secret bearer-auth ASGI middleware (`app/main.py: control_request_guard`, verified in source) **except** the 3 paths in the `SIGNED_WEBHOOK` column marked below, which instead require an HMAC request signature (`X-Signature` + `X-Timestamp` headers, TTL-bounded, verified in source at `app/api/v1/events.py`).

Legend for STATUS: IMPLEMENTED (route exists, logic is non-trivial, no placeholder markers found) / PARTIAL (route exists but has caveats noted) / PLACEHOLDER (route exists but is a stub/canned response) / MISSING / DEPRECATED / BROKEN / UNVERIFIED (route exists, behavior not exercised).

| METHOD | PATH | SERVICE (entrypoint) | AUTH | IDEMPOTENCY | RATE LIMIT | AUDIT | CALLER | STATUS |
|---|---|---|---|---|---|---|---|---|
| POST | /api/v1/events/vicidial | events (main app) | SIGNED_WEBHOOK (HMAC+TTL) | Y (idempotency_key → key_hash unique constraint) | UNVERIFIED | UNVERIFIED | VICIdial | IMPLEMENTED |
| POST | /api/v1/control/events/odoo | control | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | Odoo | IMPLEMENTED |
| POST | /api/v1/control/events/vicidial | control | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | VICIdial | IMPLEMENTED |
| GET | /api/v1/control/events/{event_id} | control | bearer | n/a (read) | UNVERIFIED | n/a | internal/UI | IMPLEMENTED |
| POST | /api/v1/control/callbacks | control | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | Odoo/agent desktop | IMPLEMENTED |
| PATCH | /api/v1/control/callbacks/{id} | control | bearer | n/a (PATCH by id) | UNVERIFIED | UNVERIFIED | Odoo/agent desktop | IMPLEMENTED |
| POST | /api/v1/control/transfers/requests | control | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | agent desktop | IMPLEMENTED |
| POST | /api/v1/control/transfers/{id}/{decision} | control | bearer | n/a | UNVERIFIED | UNVERIFIED | agent desktop/supervisor | IMPLEMENTED |
| POST | /api/v1/control/compliance/events | control | bearer | UNVERIFIED | UNVERIFIED | Y (implied by name) | VICIdial/compliance layer | IMPLEMENTED |
| POST | /api/v1/control/ai/recommendations/{id}/{decision} | control | bearer | n/a | UNVERIFIED | UNVERIFIED | AI review UI | IMPLEMENTED |
| POST | /api/v1/control/reconciliation/run | control | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | operator/scheduler | IMPLEMENTED |
| GET | /api/v1/control/reconciliation/status | control | bearer | n/a | n/a | n/a | operator | IMPLEMENTED |
| POST | /api/v1/automation/idempotency/check | automation | bearer | Y (this IS the idempotency check) | UNVERIFIED | UNVERIFIED | internal callers | IMPLEMENTED |
| POST | /api/v1/automation/audit/result | automation | bearer | UNVERIFIED | UNVERIFIED | Y (audit result ingestion) | AI/automation workers | IMPLEMENTED |
| POST | /api/v1/automation/events | automation | SIGNED_WEBHOOK (HMAC+TTL) | UNVERIFIED | UNVERIFIED | UNVERIFIED | external automation | IMPLEMENTED |
| POST | /api/v1/automation/policy-check | automation | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | policy engine caller | IMPLEMENTED |
| POST | /api/v1/automation/executions/{transition} | automation | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | workflow engine | IMPLEMENTED |
| POST | /api/v1/automation/events/dead-letter | automation | bearer | UNVERIFIED | UNVERIFIED | Y | dead-letter worker | IMPLEMENTED |
| GET | /api/v1/automation/events/{event_id} | automation | bearer | n/a | n/a | n/a | internal/UI | IMPLEMENTED |
| GET | /api/v1/automation/context/{resource}/{identifier} | automation | bearer | n/a | n/a | n/a | internal/UI | IMPLEMENTED |
| GET | /api/v1/automation/callbacks/{state} | automation | bearer | n/a | n/a | n/a | internal/UI | IMPLEMENTED |
| GET | /api/v1/automation/queues/status | automation | bearer | n/a | n/a | n/a | operator | IMPLEMENTED |
| POST | /api/v1/automation/actions/{action} | automation | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | internal callers | IMPLEMENTED |
| GET | /api/v1/reports/{report_name} | reports | bearer | n/a | UNVERIFIED | n/a | operator/Odoo | UNVERIFIED (report_name space not enumerated) |
| GET | /api/v1/operations/reliability | operations | bearer, `require_integration_admin(role)` | n/a | n/a | n/a | operator | IMPLEMENTED |
| GET | /api/v1/operations/dead-letters | operations | bearer, admin role | n/a | n/a | n/a | operator | IMPLEMENTED |
| POST | /api/v1/operations/dead-letters/{item_id}/replay | operations | bearer, admin role | should be Y given "replay" semantics — UNVERIFIED at code level | UNVERIFIED | Y (replay is itself an auditable admin action) | operator | IMPLEMENTED |
| POST | /api/v1/operations/maintenance/recover | operations | bearer, admin role | UNVERIFIED | UNVERIFIED | Y | operator | IMPLEMENTED |
| POST | /api/v1/operations/reconciliation | operations | bearer, admin role | UNVERIFIED | UNVERIFIED | Y | operator | IMPLEMENTED |
| POST | /v1/mappings/campaigns/{canonical_campaign_code} (see note) | mappings | bearer | n/a | Y (`_rate_limit`, 429 on excess) | n/a | Odoo/VICIdial adapter | IMPLEMENTED |
| GET | /v1/mappings/campaigns | mappings | bearer | n/a | Y | n/a | Odoo/VICIdial adapter | IMPLEMENTED |
| POST | /api/v2/telephony/canary | publisher | SIGNED_WEBHOOK (HMAC+TTL) | UNVERIFIED | UNVERIFIED | UNVERIFIED | telephony publisher/canary caller | IMPLEMENTED |
| POST | /v1/telephony/extensions/audit | telephony | bearer | UNVERIFIED | UNVERIFIED | Y (audit endpoint) | operator | IMPLEMENTED |
| GET | /v1/telephony/extensions/pools | telephony | bearer | n/a | n/a | n/a | provisioning UI | IMPLEMENTED |
| GET | /v1/telephony/extensions/availability | telephony | bearer | n/a | n/a | n/a | provisioning UI | IMPLEMENTED |
| POST | /v1/telephony/extensions/reserve | telephony | bearer | UNVERIFIED | UNVERIFIED | UNVERIFIED | extension-allocator | IMPLEMENTED |
| POST | /v1/telephony/provisioning | telephony | bearer | UNVERIFIED | UNVERIFIED | Y | telephony-provisioning worker | IMPLEMENTED |
| GET | /v1/telephony/provisioning/{request_id} | telephony | bearer | n/a | n/a | n/a | operator | IMPLEMENTED |
| POST | /v1/telephony/provisioning/{request_id}/activate\|suspend\|deprovision\|rollback | telephony | bearer | UNVERIFIED per-action | UNVERIFIED | Y (lifecycle actions) | operator/provisioning worker | IMPLEMENTED |
| POST | /v1/telephony/reconcile | telephony | bearer | UNVERIFIED | UNVERIFIED | Y | reconciliation worker | IMPLEMENTED |
| GET/POST | /api/v1/integrations/odoo/health, /odoo/readiness | integrations | bearer | n/a | n/a | n/a | Odoo, operator | IMPLEMENTED |
| POST | /api/v1/integrations/odoo/commands | integrations | bearer | UNVERIFIED | UNVERIFIED | Y | Odoo | IMPLEMENTED |
| GET | /api/v1/integrations/odoo/commands/{command_id} | integrations | bearer | n/a | n/a | n/a | Odoo | IMPLEMENTED |
| POST | /api/v1/integrations/n8n/dispatch, /n8n/results, /n8n/errors, /n8n/reconciliation | integrations | bearer | UNVERIFIED | UNVERIFIED | Y (results/errors imply audit) | n8n | IMPLEMENTED |
| POST | /webphone-api/v1/provision, /provision/{id}/refresh, /provision/{id}/revoke, /session, /renew, /revoke | webphone | bearer | UNVERIFIED | UNVERIFIED | should be Y (session issuance) — UNVERIFIED | agent desktop (browser-facing, via Kong) | IMPLEMENTED — **verify in `08_KONG.md`/`09_CADDY.md` that this router's `-staging` tag in code (`tags=["webphone-staging"]`) doesn't mean it's actually staging-only despite living in the production entrypoint; tag naming is inconsistent with M-3-style naming drift noted in 07_MIDDLEWARE.md** |
| GET | /webphone-api/v1/config | webphone | bearer | n/a | n/a | n/a | agent desktop | IMPLEMENTED |
| POST | /v1/n8n/runs/{run_id}/callback, /jobs/{job_id}/replay, /follow-up-proposals, /qa-reviews, /internal-alerts, /calls/{event_id}/transcription-request | n8n_staging | bearer + `require_staging()` (404s outside staging/test/integration env) | dry_run only (`{"dry_run": true}` canned response — see note) | UNVERIFIED | UNVERIFIED | n8n (non-prod only) | **PARTIAL — canned/dry-run responses by design in this router; do not treat as the real n8n integration path (that's `/api/v1/integrations/n8n/*` above)** |
| GET | /v1/n8n/test/fault/{status_code}, /test/delay/{ms} | n8n_staging | bearer + `require_staging()` | n/a | n/a | n/a | test harness only | IMPLEMENTED (intentional chaos-testing routes, non-prod gated — see finding M-4) |
| GET | /healthz, /readyz, /dependencies | runtime (all services) | none (unauthenticated, by design for health probes) | n/a | n/a | n/a | Docker healthcheck, monitoring | IMPLEMENTED, contract INCONSISTENT across services (see M-5) |
| GET | /version | runtime (only services built from `35448ef8`+) | none | n/a | n/a | n/a | monitoring/reconciliation | IMPLEMENTED but non-functional (env vars unset — see M-2) |
| GET | /metrics | main app (`make_asgi_app()`) | none (mounted unauthenticated at `/metrics`) | n/a | n/a | n/a | Prometheus | IMPLEMENTED — **flag for `08_KONG.md`: confirm `/metrics` is not exposed externally through Kong/Caddy; unauthenticated Prometheus endpoints are a common accidental-public-exposure class of bug** |

## Notes on this table
- "AUDIT: Y" above means the endpoint's evident purpose is itself an audit/compliance record (e.g. `/compliance/events`, `/dead-letters/{id}/replay`); it does **not** mean I confirmed a separate audit-log write happens on every call — that would require tracing each handler body, not done in this pass.
- Every `POST`/`PATCH` row marked "UNVERIFIED" for idempotency/rate-limit means: the route exists and is real, but I did not open that specific handler body to confirm it checks the shared `IdempotencyRecord` table or a rate limiter before acting. Given `07_MIDDLEWARE.md` finding M-6, the *primitives* for idempotency (dedicated table + check endpoint) and rate limiting (`_rate_limit` helper, 429s) demonstrably exist in this codebase — the open question per-route is adoption, not availability.
- Total middleware routes inventoried: **~62** distinct method+path combinations across 15 routers. 0 classified PLACEHOLDER or MISSING at the code level (this repo does not contain stub/TODO routes); 1 classified PARTIAL (`/v1/n8n/*` dry-run compatibility shim, which is intentionally non-authoritative per its own code comments); all others IMPLEMENTED or UNVERIFIED (meaning "exists and non-trivial, downstream behavior not exercised").
