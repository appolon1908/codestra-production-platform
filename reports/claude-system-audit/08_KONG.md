# 08 — Kong API Gateway Audit

Scope: `codestra-app` host (65.109.65.169 / 10.40.0.1). Live Kong Gateway 3.14.0.1, DB-backed
(Postgres via `kong-db`), queried read-only via Admin API (`http://127.0.0.1:8001`, GET only).
Admin API and proxy port are bound to `127.0.0.1` only (not publicly exposed) — good practice,
confirmed via `docker port codestra-kong-kong-gateway-1`.

## Inventory (live, via Admin API)

| Object | Count |
|---|---|
| Services | 19 |
| Routes | 27 |
| Plugins | 115 |
| Upstreams (load-balancer targets) | 0 — no upstream/target objects; all services point at single hosts, so Kong provides no load-balancing/health-check failover for any backend |
| Consumers | 20 |
| Certificates | 1 |
| CA certificates | 1 |

Plugin mix (enabled count): rate-limiting 26, request-size-limiting 18, key-auth 14,
request-transformer 10, correlation-id 10, cors 8, jwt 7, bot-detection 5, post/pre-function 7,
ip-restriction 4, request-termination 3, prometheus 1, file-log 1, custom
`codestra-gateway-identity` 1 (secret-file based service-to-service auth, scoped to the
`codestra-automation-gateway` service — config only references a `secret_file` path, value not
read).

Correlation-id plugin is attached to 10 of 27 routes — the rest rely on whatever the origin
service assigns as `X-Correlation-ID` (see 07_MIDDLEWARE.md for downstream correlation-ID
consistency).

## Route → auth-plugin matrix (effective: global ∪ service-scoped ∪ route-scoped)

| Route | Service | Path(s) | Auth |
|---|---|---|---|
| crm-route | codestra-crm-api | /v1/crm | key-auth |
| sms-route | codestra-sms-api | /v1/sms | key-auth |
| sms-dlr-telnexa-route | codestra-sms-dlr | /v1/sms/dlr/telnexa | key-auth |
| email-route | codestra-email-api | /v1/email | key-auth |
| webhooks-route | codestra-webhooks | /v1/webhooks | key-auth |
| website-form-* (5 routes) | codestra-website-forms | /v1/forms/* | key-auth |
| codestra-website-api-route | codestra-website-api | /api/v1/{demo,contact,pricing}-requests, analytics/events, localization/* | key-auth |
| codestra-communication-canonical-{read,write} | codestra-communication-control-plane | /api/v1/messages, /api/v1/control/messages | key-auth / jwt (mixed — write path is key-auth, one duplicate write route below is jwt) |
| codestra-communication-oauth-shadow-create | codestra-communication-control-plane | /api/v1/control/messages | jwt |
| cod-web-out-email-production | codestra-communication-control-plane | /api/v1/control/messages | jwt |
| codestra-campaign-result-submit / -policy-check | codestra-campaign-automation-api | /api/v1/integrations/n8n/results, /api/v1/automation/policy-check | jwt |
| codestra-callback-control / -read | codestra-callback-api | /api/v1/control/callbacks, /api/v1/callbacks | jwt |
| gateway-test-route | codestra-gateway-test | /v1/test | key-auth |
| **codestra-mail-api** | codestra-mail-control-plane | /api/v1/mail, /api/v1/admin/mail | **NO AUTH PLUGIN** |
| **breero-production-api-route** | breero-production-api | /health, /api/v1 | **NO AUTH PLUGIN** (mTLS Kong→upstream only) |
| **codestra-token-validation-certification** | codestra-token-validator | /v1/identity-token-certification | **NO AUTH PLUGIN** (by design — see below) |
| codestra-sms-standby-route | codestra-sms-standby | /v1/sms | NO AUTH PLUGIN → covered by **ip-restriction** (127.0.0.1, 172.19.0.1 only) |
| codestra-email-standby-route | codestra-email-standby | /v1/email | same — ip-restriction only |
| codestra-sms-webhook-standby-route | codestra-sms-webhook-standby | /v1/webhooks/sms | same — ip-restriction only |
| codestra-email-webhook-standby-route | codestra-email-webhook-standby | /v1/webhooks/email | same — ip-restriction only |

Duplicate/overlapping route note: `/api/v1/control/messages` is bound by **three separate
routes** (`codestra-communication-canonical-write` [key-auth], `codestra-communication-oauth-shadow-create`
[jwt], `cod-web-out-email-production` [jwt]) on the same service. Kong resolves route conflicts by
specificity/creation order, which is fragile — the operator has no single place to see "what
actually handles this path today" without querying the Admin API and reasoning about route
priority.

## Findings

**KONG-01 (P1) — `/api/v1/admin/mail` is missing its intended gateway-level OIDC auth plugin.**
Source of truth in the repo (`/root/codestra-production-completion/deploy/mail-platform/kong-mail-routes.yaml`,
also mirrored in `codestra-backend`/`codestra` history) declares an `openid-connect` plugin on the
`codestra-mail-control-plane` service (issuer `auth.codestra.co/realms/codestra`, audience
`codestra-mail-api`, `scopes_required: [openid]`). The **live** Kong service `b46285a8-6e36-46b9-b1ef-82a85a4124a7`
only has `request-size-limiting` attached — no `openid-connect`/`jwt`/`key-auth`. This is a real
declared-vs-runtime drift.
Mitigating factor: the FastAPI app itself (`mail_platform/api.py`) independently verifies the
bearer JWT via its own `PyJWKClient` against the same issuer/audience
(`jwt.decode(raw, key.key, algorithms=["RS256","PS256"], audience=AUDIENCE, issuer=ISSUER)`) and
enforces `require_scope("mail.admin")` + role check before returning admin data — so this is **not**
an open admin endpoint, but gateway-level defense-in-depth, consistent rate-limiting-by-consumer,
and Kong-level audit/correlation logging for this route are all absent.
Fix: apply the declared `openid-connect` plugin from `kong-mail-routes.yaml` to the live service
(`deck sync` or equivalent), or explain in docs why it was intentionally dropped.
Repo: `appolon1908-hue/codestra-production-platform` (source is currently only visible under
`/root/codestra-production-completion`, not confirmed as the same content as any cloned repo —
see 03_GITHUB_RUNTIME_RECONCILIATION.md). Suggested branch:
`fix/kong-mail-admin-openid-connect`.

**KONG-02 (P2) — `breero-production-api-route` (`/api/v1`, all methods) has no Kong-level auth,
and documentation claiming Caddy-side "401 without bearer token" could not be verified live.**
`/opt/codestra/docs/caddy/breero-oidc.md` states unauthenticated `/api/v1` requests return 401.
Caddy's `api.breero.com` site block explicitly delegates all auth to the Breero app itself
("Breero browser sessions, OIDC callbacks, and API RBAC are enforced by Breero itself") and simply
reverse-proxies to Kong on 127.0.0.1:8000, which in turn has no auth plugin on this route either.
A live read-only test (`GET https://api.breero.com/health` and `/api/v1`) both returned **503**,
not the documented 200/401 — see 09_CADDY.md and 03_GITHUB_RUNTIME_RECONCILIATION.md for the
Breero backend status. Net effect: nothing in the Codestra-controlled stack (Caddy or Kong)
enforces auth on this path; it is 100% dependent on the Breero app process being up and correct,
and that app is currently unreachable/erroring.
Fix: verify whether this is intentional architecture (fine, if documented as such and the app is
fixed) or add an ip-restriction/jwt plugin as defense-in-depth given Kong already terminates mTLS
to the upstream. Test required: live 200/401 behavior once Breero backend is restored. Rollback: none
(read-only finding). Suggested branch: `fix/breero-api-backend-503` (see also 20_PRODUCTION_BLOCKERS.md).

**KONG-03 (P3) — "standby" SMS/email/webhook services are live and reachable, not dead code.**
`codestra-kong-standby-auth` (compose project `kong-production-standby`) is Up/healthy and
resolves inside the `kong_backend` docker network. The 4 standby routes are tagged
`mock-only,no-provider-delivery` and are the only Kong routes protected purely by
`ip-restriction` (allow `127.0.0.1, 172.19.0.1` — i.e., loopback and the Docker bridge gateway,
not open to the internet) rather than key-auth/jwt. This looks like an intentional
fail-safe/rehearsal harness (mock responses so accidental hits never send real SMS/email), and the
IP restriction is appropriately tight. No action required beyond confirming with the team that
this is the intended purpose — flagged P3 only because "standby…20260820" in the tag suggests it
may be a dated one-off experiment that was never cleaned up.

**KONG-04 (P3) — No `upstreams`/`targets` objects defined anywhere.**
Every one of the 19 services points at a single static host:port. Kong provides no
load-balancing, active/passive health checks, or automatic failover for any backend through its
own upstream object model — resilience (if any) has to come entirely from the container/orchestration
layer. Not a defect per se at this traffic scale, but worth calling out given the mission's
production-readiness bar.

**KONG-05 (informational, no severity) — `codestra-token-validation-certification` route has no
auth plugin by design.** This route (`/v1/identity-token-certification` → `identity-certification`
service) is the shared token-introspection/validation endpoint other services call to validate a
bearer token (see `/opt/codestra/kong/identity-certification/TOKEN_VALIDATOR_CONTRACT.md`) — an
endpoint of this kind legitimately can't require the caller to already hold a valid token. Not
independently verified whether it rate-limits/logs enough to prevent use as a token-guessing
oracle; recommend a follow-up read of `TOKEN_VALIDATOR_CONTRACT.md` and the service's own rate
limits (route has no explicit rate-limiting plugin visible in the dump — only two global
rate-limiting plugins exist and their route/service scope wasn't fully enumerated here). Mark
**UNVERIFIED** whether a global rate-limit plugin actually covers this route.

## Not verified in this pass (time-boxed single fork covering Kong+Caddy+Keycloak)
- CORS plugin configs (8 instances) were not individually reviewed for overly-broad `Access-Control-Allow-Origin: *`.
- Full 115-plugin list was not exhaustively cross-checked route-by-route beyond auth/ip-restriction/bot-detection.
- `codestra-gateway-identity` custom plugin's actual verification logic (Lua source) was not read — only its declared config surface.
- Kong→Postgres connection encryption (`KONG_PG_*` env showed no explicit TLS flag) not confirmed either way.

## GitHub repository
`appolon1908-hue/codestra-production-platform` (Kong declarative fragments found under
`/opt/codestra/kong/` and mail-specific ones under a separate mail-platform tree — reconciliation
with actual GitHub repo/branch pending 03_GITHUB_RUNTIME_RECONCILIATION.md).
